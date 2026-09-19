from __future__ import annotations

from dataclasses import dataclass
import math
from math import gcd
from typing import Iterable

import numpy as np

from simulator.floorplanner import FloorplanResult


class InterconnectDynamicsError(ValueError):
    """Raised when finite-capacity interconnect assumptions are invalid."""


Cell = tuple[int, int]


@dataclass(frozen=True)
class TransportBatchSchedule:
    completion_steps: dict[int, int]
    max_completion_steps: int
    reserved_cell_time_slots: int


@dataclass(frozen=True)
class TransportRiskResult:
    probability_any_starvation: float
    expected_starved_service_slots: float
    expected_stall_intervals: float
    expected_overflow_states: float
    expected_stall_extension_seconds: float
    event_interval_ns: int
    logical_step_ns: int
    service_period_events: int
    quantized_horizon_seconds: float
    max_single_batch_transport_latency_ns: int
    max_all_success_transport_latency_ns: int
    lane_capacity_states_per_logical_step: int
    transport_spill_across_factory_event: bool


def factory_paths_from_floorplan(
    floorplan: FloorplanResult,
) -> dict[int, tuple[Cell, ...]]:
    paths: dict[int, tuple[Cell, ...]] = {}

    for route in floorplan.routes:
        if not route.source.startswith("factory_"):
            continue
        factory_id = int(route.source.split("_", 1)[1])
        paths[factory_id] = route.path

    expected = {
        int(placement.name.split("_", 1)[1])
        for placement in floorplan.placements
        if placement.role == "factory"
    }
    if set(paths) != expected:
        raise InterconnectDynamicsError(
            "floorplan does not contain exactly one routed path per factory."
        )

    if any(len(path) == 0 for path in paths.values()):
        raise InterconnectDynamicsError(
            "factory transport paths must contain at least one corridor cell."
        )

    return paths


def schedule_successful_batches(
    *,
    factory_paths: dict[int, tuple[Cell, ...]],
    successful_factories: Iterable[int],
    output_states_per_batch: int,
    lane_capacity_states_per_logical_step: int,
) -> TransportBatchSchedule:
    """
    Deterministic pipelined state transport over route cells.

    Each logical step, a route cell can carry at most
    lane_capacity_states_per_logical_step states. Individual magic states are
    scheduled round-robin by token index then factory ID, so simultaneously
    successful factories do not receive a hidden priority based on batch size.

    A state advances one path cell per logical step. A batch becomes available
    to the shared buffer only after all states from that successful factory have
    completed transport, preserving the earlier all-or-nothing batch semantics.
    """
    if output_states_per_batch <= 0:
        raise InterconnectDynamicsError(
            "output_states_per_batch must be > 0."
        )
    if lane_capacity_states_per_logical_step <= 0:
        raise InterconnectDynamicsError(
            "lane_capacity_states_per_logical_step must be > 0."
        )

    successful = tuple(sorted(set(successful_factories)))
    if any(factory_id not in factory_paths for factory_id in successful):
        raise InterconnectDynamicsError(
            "successful factory is missing from factory_paths."
        )

    if not successful:
        return TransportBatchSchedule(
            completion_steps={},
            max_completion_steps=0,
            reserved_cell_time_slots=0,
        )

    reservations: dict[tuple[Cell, int], int] = {}
    completion: dict[int, int] = {
        factory_id: 0 for factory_id in successful
    }

    for token_index in range(output_states_per_batch):
        for factory_id in successful:
            path = factory_paths[factory_id]
            start = 0

            while True:
                conflict = False
                for hop, cell in enumerate(path):
                    occupancy = reservations.get((cell, start + hop), 0)
                    if occupancy >= lane_capacity_states_per_logical_step:
                        conflict = True
                        break
                if not conflict:
                    break
                start += 1

            for hop, cell in enumerate(path):
                key = (cell, start + hop)
                reservations[key] = reservations.get(key, 0) + 1

            delivery_step = start + len(path)
            completion[factory_id] = max(
                completion[factory_id],
                delivery_step,
            )

    return TransportBatchSchedule(
        completion_steps=completion,
        max_completion_steps=max(completion.values()),
        reserved_cell_time_slots=len(reservations),
    )


def _cumulative_service_slots(
    *,
    target_states: int,
    nominal_runtime_ns: int,
    time_ns: int,
) -> int:
    if time_ns <= 0:
        return 0
    if time_ns >= nominal_runtime_ns:
        return target_states
    return (target_states * time_ns) // nominal_runtime_ns


def _service_between(
    *,
    target_states: int,
    nominal_runtime_ns: int,
    start_ns: int,
    end_ns: int,
) -> int:
    if end_ns < start_ns:
        raise InterconnectDynamicsError("end_ns must be >= start_ns.")
    return (
        _cumulative_service_slots(
            target_states=target_states,
            nominal_runtime_ns=nominal_runtime_ns,
            time_ns=end_ns,
        )
        - _cumulative_service_slots(
            target_states=target_states,
            nominal_runtime_ns=nominal_runtime_ns,
            time_ns=start_ns,
        )
    )


def _branch_outcome(
    *,
    buffer_before: int,
    capacity_states: int,
    target_states: int,
    nominal_runtime_ns: int,
    event_start_ns: int,
    event_end_ns: int,
    deliveries: tuple[tuple[int, int], ...],
) -> tuple[int, int, int, int]:
    buffer_states = buffer_before
    missed_total = 0
    stall_intervals = 0
    overflow_total = 0
    previous_time = event_start_ns

    for delivery_time, produced_states in sorted(deliveries):
        service_slots = _service_between(
            target_states=target_states,
            nominal_runtime_ns=nominal_runtime_ns,
            start_ns=previous_time,
            end_ns=delivery_time,
        )
        served = min(buffer_states, service_slots)
        missed = service_slots - served
        if missed > 0:
            missed_total += missed
            stall_intervals += 1
        buffer_states -= served

        room = capacity_states - buffer_states
        accepted = min(room, produced_states)
        buffer_states += accepted
        overflow_total += produced_states - accepted
        previous_time = delivery_time

    service_slots = _service_between(
        target_states=target_states,
        nominal_runtime_ns=nominal_runtime_ns,
        start_ns=previous_time,
        end_ns=event_end_ns,
    )
    served = min(buffer_states, service_slots)
    missed = service_slots - served
    if missed > 0:
        missed_total += missed
        stall_intervals += 1
    buffer_states -= served

    return (
        buffer_states,
        missed_total,
        stall_intervals,
        overflow_total,
    )


def _event_matrices(
    *,
    capacity_states: int,
    target_states: int,
    nominal_runtime_ns: int,
    event_start_ns: int,
    event_end_ns: int,
    branches: tuple[tuple[float, tuple[tuple[int, int], ...]], ...],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return:
      Q: absorbing-starvation transition matrix
      A: augmented full transition matrix accumulating exact expected rewards
         (missed service slots, stall intervals, overflow states)
    """
    normal_states = capacity_states + 1
    starvation_state = normal_states
    rewards_count = 3

    Q = np.zeros((normal_states + 1, normal_states + 1), dtype=float)
    P = np.zeros((normal_states, normal_states), dtype=float)
    rewards = np.zeros((normal_states, rewards_count), dtype=float)

    for buffer_before in range(normal_states):
        for probability, deliveries in branches:
            (
                buffer_after,
                missed,
                stalls,
                overflow,
            ) = _branch_outcome(
                buffer_before=buffer_before,
                capacity_states=capacity_states,
                target_states=target_states,
                nominal_runtime_ns=nominal_runtime_ns,
                event_start_ns=event_start_ns,
                event_end_ns=event_end_ns,
                deliveries=deliveries,
            )

            P[buffer_before, buffer_after] += probability
            rewards[buffer_before, 0] += probability * missed
            rewards[buffer_before, 1] += probability * stalls
            rewards[buffer_before, 2] += probability * overflow

            if missed > 0:
                Q[buffer_before, starvation_state] += probability
            else:
                Q[buffer_before, buffer_after] += probability

    Q[starvation_state, starvation_state] = 1.0

    A = np.zeros(
        (normal_states + rewards_count, normal_states + rewards_count),
        dtype=float,
    )
    A[:normal_states, :normal_states] = P
    A[:normal_states, normal_states:] = rewards
    A[normal_states:, normal_states:] = np.eye(rewards_count)

    return Q, A


def _compose(matrices: list[np.ndarray]) -> np.ndarray:
    if not matrices:
        raise InterconnectDynamicsError(
            "at least one matrix is required for composition."
        )
    result = np.eye(matrices[0].shape[0])
    for matrix in matrices:
        result = result @ matrix
    return result


def analyze_transport_aware_starvation(
    *,
    floorplan: FloorplanResult,
    target_states: int,
    nominal_runtime_ns: int,
    batch_duration_ns: int,
    factories: int,
    phase_policy: str,
    output_states_per_batch: int,
    batch_success_probability: float,
    capacity_states: int,
    initial_buffer_states: int,
    logical_step_ns: int,
    lane_capacity_states_per_logical_step: int,
    max_service_period_events: int = 10000,
) -> TransportRiskResult:
    """
    Exact starvation/reward analysis with finite-capacity routed transport.

    Scope guardrail:
    every successful batch must finish transport before the next factory
    completion event. If it does not, the current no-carry transport kernel
    refuses the candidate rather than dropping in-flight state.
    """
    if factories <= 0:
        raise InterconnectDynamicsError("factories must be > 0.")
    if target_states <= 0:
        raise InterconnectDynamicsError("target_states must be > 0.")
    if nominal_runtime_ns <= 0:
        raise InterconnectDynamicsError("nominal_runtime_ns must be > 0.")
    if batch_duration_ns <= 0:
        raise InterconnectDynamicsError("batch_duration_ns must be > 0.")
    if logical_step_ns <= 0:
        raise InterconnectDynamicsError("logical_step_ns must be > 0.")
    if not 0 < batch_success_probability <= 1:
        raise InterconnectDynamicsError(
            "batch_success_probability must be in (0, 1]."
        )
    if not 0 <= initial_buffer_states <= capacity_states:
        raise InterconnectDynamicsError(
            "initial_buffer_states must be within the buffer."
        )
    if phase_policy not in ("synchronized", "even_staggered"):
        raise InterconnectDynamicsError(
            "phase_policy must be synchronized or even_staggered."
        )

    factory_paths = factory_paths_from_floorplan(floorplan)
    if len(factory_paths) != factories:
        raise InterconnectDynamicsError(
            "factory_count does not match floorplan factory routes."
        )

    if phase_policy == "synchronized":
        event_interval_ns = batch_duration_ns
    else:
        if batch_duration_ns % factories != 0:
            raise InterconnectDynamicsError(
                "even_staggered requires integer event interval."
            )
        event_interval_ns = batch_duration_ns // factories

    single_latencies_steps = {
        factory_id: schedule_successful_batches(
            factory_paths=factory_paths,
            successful_factories=(factory_id,),
            output_states_per_batch=output_states_per_batch,
            lane_capacity_states_per_logical_step=(
                lane_capacity_states_per_logical_step
            ),
        ).max_completion_steps
        for factory_id in sorted(factory_paths)
    }
    max_single_latency_ns = (
        max(single_latencies_steps.values()) * logical_step_ns
    )

    all_success = schedule_successful_batches(
        factory_paths=factory_paths,
        successful_factories=tuple(sorted(factory_paths)),
        output_states_per_batch=output_states_per_batch,
        lane_capacity_states_per_logical_step=(
            lane_capacity_states_per_logical_step
        ),
    )
    max_all_success_latency_ns = (
        all_success.max_completion_steps * logical_step_ns
    )

    max_required_latency = (
        max_all_success_latency_ns
        if phase_policy == "synchronized"
        else max_single_latency_ns
    )
    spill = max_required_latency >= event_interval_ns
    if spill:
        raise InterconnectDynamicsError(
            "transport spill across factory event: current exact kernel "
            "does not carry in-flight batches between events."
        )

    sync_branches: tuple[
        tuple[float, tuple[tuple[int, int], ...]], ...
    ] | None = None

    if phase_policy == "synchronized":
        branch_items: list[
            tuple[float, tuple[tuple[int, int], ...]]
        ] = []
        factory_ids = tuple(sorted(factory_paths))

        for mask in range(1 << factories):
            successful = tuple(
                factory_ids[index]
                for index in range(factories)
                if mask & (1 << index)
            )
            success_count = len(successful)
            probability = (
                batch_success_probability**success_count
                * (1.0 - batch_success_probability)
                ** (factories - success_count)
            )

            schedule = schedule_successful_batches(
                factory_paths=factory_paths,
                successful_factories=successful,
                output_states_per_batch=output_states_per_batch,
                lane_capacity_states_per_logical_step=(
                    lane_capacity_states_per_logical_step
                ),
            )
            deliveries = tuple(
                sorted(
                    (
                        steps * logical_step_ns,
                        output_states_per_batch,
                    )
                    for steps in schedule.completion_steps.values()
                )
            )
            branch_items.append((probability, deliveries))

        sync_branches = tuple(branch_items)

    service_period = nominal_runtime_ns // gcd(
        target_states * event_interval_ns,
        nominal_runtime_ns,
    )
    factory_period = factories if phase_policy == "even_staggered" else 1
    period_events = math.lcm(service_period, factory_period)

    if period_events > max_service_period_events:
        raise InterconnectDynamicsError(
            "transport-aware service period exceeds configured maximum."
        )

    normal_states = capacity_states + 1
    rewards_count = 3

    risk_vector = np.zeros(normal_states + 1, dtype=float)
    risk_vector[initial_buffer_states] = 1.0

    reward_vector = np.zeros(normal_states + rewards_count, dtype=float)
    reward_vector[initial_buffer_states] = 1.0

    initial_end = min(event_interval_ns, nominal_runtime_ns)
    initial_Q, initial_A = _event_matrices(
        capacity_states=capacity_states,
        target_states=target_states,
        nominal_runtime_ns=nominal_runtime_ns,
        event_start_ns=0,
        event_end_ns=initial_end,
        branches=((1.0, ()),),
    )
    risk_vector = risk_vector @ initial_Q
    reward_vector = reward_vector @ initial_A

    full_intervals = nominal_runtime_ns // event_interval_ns
    remainder_ns = nominal_runtime_ns % event_interval_ns
    bulk_events = max(0, full_intervals - 1)

    phase_Q: list[np.ndarray] = []
    phase_A: list[np.ndarray] = []

    for event_index in range(1, period_events + 1):
        start_ns = event_index * event_interval_ns
        end_ns = start_ns + event_interval_ns

        if phase_policy == "synchronized":
            assert sync_branches is not None
            branches = tuple(
                (
                    probability,
                    tuple(
                        (
                            start_ns + relative_ns,
                            states,
                        )
                        for relative_ns, states in deliveries
                    ),
                )
                for probability, deliveries in sync_branches
            )
        else:
            active_factory = ((event_index - 1) % factories) + 1
            relative_ns = (
                single_latencies_steps[active_factory] * logical_step_ns
            )
            branches = (
                (1.0 - batch_success_probability, ()),
                (
                    batch_success_probability,
                    (
                        (
                            start_ns + relative_ns,
                            output_states_per_batch,
                        ),
                    ),
                ),
            )

        Q, A = _event_matrices(
            capacity_states=capacity_states,
            target_states=target_states,
            nominal_runtime_ns=nominal_runtime_ns,
            event_start_ns=start_ns,
            event_end_ns=end_ns,
            branches=branches,
        )
        phase_Q.append(Q)
        phase_A.append(A)

    if bulk_events > 0:
        full_periods, tail_phases = divmod(
            bulk_events,
            period_events,
        )

        if full_periods:
            period_Q = _compose(phase_Q)
            period_A = _compose(phase_A)
            risk_vector = risk_vector @ np.linalg.matrix_power(
                period_Q,
                full_periods,
            )
            reward_vector = reward_vector @ np.linalg.matrix_power(
                period_A,
                full_periods,
            )

        for index in range(tail_phases):
            risk_vector = risk_vector @ phase_Q[index]
            reward_vector = reward_vector @ phase_A[index]

    if remainder_ns:
        event_index = full_intervals
        start_ns = event_index * event_interval_ns
        end_ns = (event_index + 1) * event_interval_ns

        phase_index = (event_index - 1) % period_events
        # Rebuild using the real absolute time because consumer demand saturates
        # at nominal_runtime_ns inside this final quantized interval.
        if phase_policy == "synchronized":
            assert sync_branches is not None
            branches = tuple(
                (
                    probability,
                    tuple(
                        (
                            start_ns + relative_ns,
                            states,
                        )
                        for relative_ns, states in deliveries
                    ),
                )
                for probability, deliveries in sync_branches
            )
        else:
            active_factory = ((event_index - 1) % factories) + 1
            relative_ns = (
                single_latencies_steps[active_factory] * logical_step_ns
            )
            branches = (
                (1.0 - batch_success_probability, ()),
                (
                    batch_success_probability,
                    (
                        (
                            start_ns + relative_ns,
                            output_states_per_batch,
                        ),
                    ),
                ),
            )

        tail_Q, tail_A = _event_matrices(
            capacity_states=capacity_states,
            target_states=target_states,
            nominal_runtime_ns=nominal_runtime_ns,
            event_start_ns=start_ns,
            event_end_ns=end_ns,
            branches=branches,
        )
        risk_vector = risk_vector @ tail_Q
        reward_vector = reward_vector @ tail_A

    probability_any_starvation = float(risk_vector[-1])
    rewards = reward_vector[normal_states:]

    expected_missed = float(rewards[0])
    expected_stalls = float(rewards[1])
    expected_overflow = float(rewards[2])

    nominal_runtime_seconds = nominal_runtime_ns / 1_000_000_000
    consumer_rate = target_states / nominal_runtime_seconds
    expected_stall_extension = expected_missed / consumer_rate

    intervals = (
        full_intervals + (1 if remainder_ns else 0)
    )
    quantized_horizon_seconds = (
        intervals * event_interval_ns / 1_000_000_000
    )

    return TransportRiskResult(
        probability_any_starvation=probability_any_starvation,
        expected_starved_service_slots=expected_missed,
        expected_stall_intervals=expected_stalls,
        expected_overflow_states=expected_overflow,
        expected_stall_extension_seconds=expected_stall_extension,
        event_interval_ns=event_interval_ns,
        logical_step_ns=logical_step_ns,
        service_period_events=period_events,
        quantized_horizon_seconds=quantized_horizon_seconds,
        max_single_batch_transport_latency_ns=max_single_latency_ns,
        max_all_success_transport_latency_ns=max_all_success_latency_ns,
        lane_capacity_states_per_logical_step=(
            lane_capacity_states_per_logical_step
        ),
        transport_spill_across_factory_event=False,
    )
