from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

import numpy as np

from simulator.buffer_risk import build_service_schedule


PhasePolicy = Literal["synchronized", "even_staggered"]


class MultiFactoryError(ValueError):
    """Raised when multi-factory model inputs are invalid."""


@dataclass(frozen=True)
class MultiFactoryStartupCost:
    initial_buffer_states: int
    successful_batches_required: int
    expected_prefill_seconds: float
    phase_setup_seconds: float
    conservative_startup_seconds: float
    accounting_model: str


@dataclass(frozen=True)
class MultiFactoryRiskKernel:
    transition: np.ndarray
    capacity_states: int
    event_interval_ns: int
    batches_in_horizon: int
    service_period_events: int
    final_service_slots: int
    phase_policy: str
    event_order: str

    def probability_any_starvation(self, *, initial_buffer_states: int) -> float:
        if not 0 <= initial_buffer_states <= self.capacity_states:
            raise MultiFactoryError(
                "initial_buffer_states must be between 0 and capacity_states."
            )

        vector = np.zeros(self.capacity_states + 2, dtype=float)
        vector[initial_buffer_states] = 1.0
        final = vector @ self.transition
        risk = float(final[-1])
        return min(1.0, max(0.0, risk))


def _validate_phase_policy(policy: str) -> PhasePolicy:
    if policy not in ("synchronized", "even_staggered"):
        raise MultiFactoryError(
            "phase_policy must be 'synchronized' or 'even_staggered'."
        )
    return policy  # type: ignore[return-value]


def _binomial_arrivals(
    *,
    factories: int,
    batch_success_probability: float,
    output_states_per_successful_batch: int,
) -> tuple[tuple[float, int], ...]:
    return tuple(
        (
            math.comb(factories, successes)
            * batch_success_probability**successes
            * (1.0 - batch_success_probability) ** (factories - successes),
            successes * output_states_per_successful_batch,
        )
        for successes in range(factories + 1)
    )


def _bernoulli_arrivals(
    *,
    batch_success_probability: float,
    output_states_per_successful_batch: int,
) -> tuple[tuple[float, int], ...]:
    return (
        (1.0 - batch_success_probability, 0),
        (batch_success_probability, output_states_per_successful_batch),
    )


def factory_event_interval_ns(
    *,
    batch_duration_ns: int,
    factories: int,
    phase_policy: str,
) -> int:
    policy = _validate_phase_policy(phase_policy)
    if batch_duration_ns <= 0:
        raise MultiFactoryError("batch_duration_ns must be > 0.")
    if factories <= 0:
        raise MultiFactoryError("factories must be > 0.")

    if policy == "synchronized":
        return batch_duration_ns

    if batch_duration_ns % factories != 0:
        raise MultiFactoryError(
            "even_staggered requires batch_duration_ns divisible by factories."
        )
    return batch_duration_ns // factories


def phase_setup_seconds(
    *,
    batch_duration_seconds: float,
    factories: int,
    phase_policy: str,
) -> float:
    policy = _validate_phase_policy(phase_policy)
    if batch_duration_seconds <= 0:
        raise MultiFactoryError("batch_duration_seconds must be > 0.")
    if factories <= 0:
        raise MultiFactoryError("factories must be > 0.")

    if policy == "synchronized" or factories == 1:
        return 0.0

    return batch_duration_seconds * (factories - 1) / factories


def expected_parallel_prefill_rounds(
    *,
    successful_batches_required: int,
    factories: int,
    batch_success_probability: float,
) -> float:
    """
    Exact expected synchronized rounds to accumulate enough successful batches.

    Each round contains one independent batch attempt per factory. The recurrence
    accounts for multiple successes arriving in the same round.
    """
    if successful_batches_required < 0:
        raise MultiFactoryError("successful_batches_required must be >= 0.")
    if factories <= 0:
        raise MultiFactoryError("factories must be > 0.")
    if not 0 < batch_success_probability <= 1:
        raise MultiFactoryError(
            "batch_success_probability must be in the interval (0, 1]."
        )
    if successful_batches_required == 0:
        return 0.0

    probabilities = tuple(
        math.comb(factories, successes)
        * batch_success_probability**successes
        * (1.0 - batch_success_probability) ** (factories - successes)
        for successes in range(factories + 1)
    )
    p_zero = probabilities[0]
    if p_zero >= 1.0:
        raise MultiFactoryError("Synchronized prefill cannot make progress.")

    expected = [0.0] * (successful_batches_required + 1)

    for remaining in range(1, successful_batches_required + 1):
        continuation = 0.0
        for successes in range(1, factories + 1):
            continuation += probabilities[successes] * expected[
                max(0, remaining - successes)
            ]
        expected[remaining] = (1.0 + continuation) / (1.0 - p_zero)

    return expected[successful_batches_required]


def multi_factory_startup_cost(
    *,
    initial_buffer_states: int,
    factories: int,
    phase_policy: str,
    batch_duration_seconds: float,
    output_states_per_successful_batch: int,
    batch_success_probability: float,
) -> MultiFactoryStartupCost:
    policy = _validate_phase_policy(phase_policy)
    if initial_buffer_states < 0:
        raise MultiFactoryError("initial_buffer_states must be >= 0.")
    if output_states_per_successful_batch <= 0:
        raise MultiFactoryError(
            "output_states_per_successful_batch must be > 0."
        )

    successes_required = math.ceil(
        initial_buffer_states / output_states_per_successful_batch
    )

    phase_setup = phase_setup_seconds(
        batch_duration_seconds=batch_duration_seconds,
        factories=factories,
        phase_policy=policy,
    )

    if successes_required == 0:
        expected_prefill = 0.0
    elif policy == "synchronized":
        rounds = expected_parallel_prefill_rounds(
            successful_batches_required=successes_required,
            factories=factories,
            batch_success_probability=batch_success_probability,
        )
        expected_prefill = rounds * batch_duration_seconds
    else:
        event_interval = batch_duration_seconds / factories
        expected_prefill = (
            successes_required / batch_success_probability
        ) * event_interval

    return MultiFactoryStartupCost(
        initial_buffer_states=initial_buffer_states,
        successful_batches_required=successes_required,
        expected_prefill_seconds=expected_prefill,
        phase_setup_seconds=phase_setup,
        conservative_startup_seconds=expected_prefill + phase_setup,
        accounting_model="phase_setup_plus_prefill_no_overlap_conservative",
    )


def _failure_transition_matrix(
    *,
    capacity_states: int,
    service_slots: int,
    arrivals: tuple[tuple[float, int], ...],
) -> np.ndarray:
    """
    One event-step transition with an absorbing starvation state.

    Event order is intentionally causal and conservative:
      1. consumer demand accrued since the previous factory event is served;
      2. if demand cannot be met, the trajectory enters the starvation state;
      3. the new factory output is then admitted to the bounded shared buffer.

    This prevents a batch completing at the end of an interval from satisfying
    demand that occurred earlier in that interval.
    """
    if capacity_states <= 0:
        raise MultiFactoryError("capacity_states must be > 0.")
    if service_slots < 0:
        raise MultiFactoryError("service_slots must be >= 0.")

    normal_states = capacity_states + 1
    starvation_state = normal_states
    matrix = np.zeros((normal_states + 1, normal_states + 1), dtype=float)

    for buffer_before in range(normal_states):
        served = min(buffer_before, service_slots)
        missed = service_slots - served
        buffer_after_service = buffer_before - served

        for probability, produced in arrivals:
            if missed > 0:
                matrix[buffer_before, starvation_state] += probability
                continue

            buffer_after = min(
                capacity_states,
                buffer_after_service + produced,
            )
            matrix[buffer_before, buffer_after] += probability

    matrix[starvation_state, starvation_state] = 1.0
    return matrix


def _compose(matrices: list[np.ndarray]) -> np.ndarray:
    if not matrices:
        raise MultiFactoryError("At least one transition matrix is required.")

    result = np.eye(matrices[0].shape[0])
    for matrix in matrices:
        result = result @ matrix
    return result


def build_multi_factory_risk_kernel(
    *,
    target_states: int,
    nominal_runtime_ns: int,
    batch_duration_ns: int,
    factories: int,
    phase_policy: str,
    output_states_per_successful_batch: int,
    batch_success_probability: float,
    capacity_states: int,
) -> MultiFactoryRiskKernel:
    """
    Build an exact finite-state starvation kernel for a shared buffer.

    synchronized:
      all factories complete together once per protocol batch; arrival count is
      Binomial(factories, p).

    even_staggered:
      factory phases are evenly spaced; one factory completes per event interval
      and each event is Bernoulli(p).

    The model is exact within these timing and independence assumptions.
    """
    policy = _validate_phase_policy(phase_policy)
    if factories <= 0:
        raise MultiFactoryError("factories must be > 0.")
    if output_states_per_successful_batch <= 0:
        raise MultiFactoryError(
            "output_states_per_successful_batch must be > 0."
        )
    if not 0 < batch_success_probability <= 1:
        raise MultiFactoryError(
            "batch_success_probability must be in the interval (0, 1]."
        )

    event_interval = factory_event_interval_ns(
        batch_duration_ns=batch_duration_ns,
        factories=factories,
        phase_policy=policy,
    )

    if policy == "synchronized":
        arrivals = _binomial_arrivals(
            factories=factories,
            batch_success_probability=batch_success_probability,
            output_states_per_successful_batch=(
                output_states_per_successful_batch
            ),
        )
    else:
        arrivals = _bernoulli_arrivals(
            batch_success_probability=batch_success_probability,
            output_states_per_successful_batch=(
                output_states_per_successful_batch
            ),
        )

    schedule = build_service_schedule(
        target_states=target_states,
        nominal_runtime_ns=nominal_runtime_ns,
        batch_duration_ns=event_interval,
    )

    cache: dict[int, np.ndarray] = {}

    def matrix(service_slots: int) -> np.ndarray:
        if service_slots not in cache:
            cache[service_slots] = _failure_transition_matrix(
                capacity_states=capacity_states,
                service_slots=service_slots,
                arrivals=arrivals,
            )
        return cache[service_slots]

    period = _compose([matrix(slots) for slots in schedule.pattern])
    full = np.linalg.matrix_power(
        period,
        schedule.full_periods_before_final,
    )

    for slots in schedule.remainder_before_final:
        full = full @ matrix(slots)

    full = full @ matrix(schedule.final_service_slots)

    return MultiFactoryRiskKernel(
        transition=full,
        capacity_states=capacity_states,
        event_interval_ns=event_interval,
        batches_in_horizon=schedule.batches_in_horizon,
        service_period_events=len(schedule.pattern),
        final_service_slots=schedule.final_service_slots,
        phase_policy=policy,
        event_order="consumer_then_factory",
    )
