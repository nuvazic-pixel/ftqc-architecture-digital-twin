from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from statistics import mean
from typing import Iterable


class BackpressureNetworkError(ValueError):
    """Raised when finite-buffer interconnect inputs are invalid."""


Cell = tuple[int, int]
QueueKey = tuple[int, int]


@dataclass(frozen=True)
class NetworkToken:
    batch_id: str
    factory_id: int
    token_index: int
    generation_tick: int


@dataclass
class PendingFactoryBatch:
    batch_id: str
    factory_id: int
    generation_tick: int
    tokens: deque[NetworkToken]


@dataclass
class CellService:
    token: NetworkToken
    feeder: QueueKey
    finish_tick: int


@dataclass(frozen=True)
class DeliveredBatch:
    batch_id: str
    factory_id: int
    generation_tick: int
    completion_tick: int
    token_count: int

    @property
    def latency_ticks(self) -> int:
        return self.completion_tick - self.generation_tick


@dataclass(frozen=True)
class BackpressureTraceSummary:
    scheduled_factory_events: int
    generated_batches: int
    suppressed_factory_events: int
    generated_states: int
    delivered_states: int
    max_network_states: int
    max_injection_queue_occupancy: int
    max_intermediate_queue_occupancy: int
    injection_queue_full_ticks: int
    intermediate_queue_full_ticks: int
    factory_output_backpressure_ticks: int
    blocked_after_service_ticks: int
    max_carryover_batches_at_event_boundary: int
    event_boundaries_with_carryover: int
    fraction_event_boundaries_with_carryover: float
    mean_batch_latency_ticks: float
    p95_batch_latency_ticks: int
    max_batch_latency_ticks: int
    drain_tail_ticks: int
    busiest_cell_busy_ticks: int
    busiest_cell_utilization_during_generation_horizon: float
    total_cell_busy_ticks: int
    all_generated_states_delivered: bool


class FiniteBufferBackpressureNetwork:
    """
    Deterministic finite-buffer routed network with blocking backpressure.

    Each factory route is a sequence of physical corridor cells. Tokens wait in
    a finite queue before each hop. The first queue is the factory injection
    queue; later queues are finite intermediate node buffers.

    A cell holds at most one token. When service finishes, the token cannot
    leave the cell until the downstream queue has free capacity. During that
    blocked-after-service interval, the cell remains occupied and upstream
    traffic cannot use it. This is explicit backpressure.

    A completed factory batch has one finite output staging record. If that
    record has not drained into the injection queue by the next nominal factory
    completion, the new completion event is suppressed and counted as a
    backpressure stall instead of being hidden in an unbounded source queue.
    """

    def __init__(
        self,
        *,
        factory_paths: dict[int, tuple[Cell, ...]],
        injection_queue_capacity_states: int,
        intermediate_queue_capacity_states: int,
        injection_bandwidth_states_per_tick: int,
        hop_latency_ticks: int,
    ) -> None:
        if not factory_paths:
            raise BackpressureNetworkError(
                "factory_paths must not be empty."
            )
        if any(not path for path in factory_paths.values()):
            raise BackpressureNetworkError(
                "every factory path must contain at least one cell."
            )
        if injection_queue_capacity_states <= 0:
            raise BackpressureNetworkError(
                "injection_queue_capacity_states must be > 0."
            )
        if intermediate_queue_capacity_states <= 0:
            raise BackpressureNetworkError(
                "intermediate_queue_capacity_states must be > 0."
            )
        if injection_bandwidth_states_per_tick <= 0:
            raise BackpressureNetworkError(
                "injection_bandwidth_states_per_tick must be > 0."
            )
        if hop_latency_ticks <= 0:
            raise BackpressureNetworkError(
                "hop_latency_ticks must be > 0."
            )

        self.factory_paths = {
            int(factory_id): tuple(path)
            for factory_id, path in factory_paths.items()
        }
        self.injection_queue_capacity_states = (
            injection_queue_capacity_states
        )
        self.intermediate_queue_capacity_states = (
            intermediate_queue_capacity_states
        )
        self.injection_bandwidth_states_per_tick = (
            injection_bandwidth_states_per_tick
        )
        self.hop_latency_ticks = hop_latency_ticks

        self._queues: dict[QueueKey, deque[NetworkToken]] = {}
        self._queue_capacities: dict[QueueKey, int] = {}
        self._cell_feeders: dict[Cell, list[QueueKey]] = {}

        for factory_id, path in sorted(self.factory_paths.items()):
            for hop_index, cell in enumerate(path):
                key = (factory_id, hop_index)
                self._queues[key] = deque()
                self._queue_capacities[key] = (
                    injection_queue_capacity_states
                    if hop_index == 0
                    else intermediate_queue_capacity_states
                )
                self._cell_feeders.setdefault(cell, []).append(key)

        for cell in self._cell_feeders:
            self._cell_feeders[cell].sort()

        self._cell_services: dict[Cell, CellService | None] = {
            cell: None for cell in self._cell_feeders
        }
        self._arbiter_pointer: dict[Cell, int] = {
            cell: 0 for cell in self._cell_feeders
        }
        self._cell_busy_ticks: dict[Cell, int] = {
            cell: 0 for cell in self._cell_feeders
        }

        self._pending_factory: dict[int, PendingFactoryBatch | None] = {
            factory_id: None for factory_id in self.factory_paths
        }

        self._batch_remaining: dict[str, int] = {}
        self._batch_generation: dict[str, tuple[int, int, int]] = {}
        self._delivered_batches: list[DeliveredBatch] = []

        self.scheduled_factory_events = 0
        self.generated_batches = 0
        self.suppressed_factory_events = 0
        self.generated_states = 0
        self.delivered_states = 0

        self.max_network_states = 0
        self.max_injection_queue_occupancy = 0
        self.max_intermediate_queue_occupancy = 0
        self.injection_queue_full_ticks = 0
        self.intermediate_queue_full_ticks = 0
        self.factory_output_backpressure_ticks = 0
        self.blocked_after_service_ticks = 0

        self.max_carryover_batches_at_event_boundary = 0
        self.event_boundaries_with_carryover = 0
        self._event_boundary_count = 0

    @property
    def delivered_batches(self) -> tuple[DeliveredBatch, ...]:
        return tuple(self._delivered_batches)

    def _queue_capacity(self, key: QueueKey) -> int:
        return self._queue_capacities[key]

    def _queue_has_room(self, key: QueueKey) -> bool:
        return len(self._queues[key]) < self._queue_capacity(key)

    def _record_event_boundary(self, tick: int) -> None:
        carryover = sum(
            generation_tick < tick and batch_id in self._batch_remaining
            for batch_id, (
                _factory_id,
                generation_tick,
                _token_count,
            ) in self._batch_generation.items()
        )
        self._event_boundary_count += 1
        if carryover > 0:
            self.event_boundaries_with_carryover += 1
        self.max_carryover_batches_at_event_boundary = max(
            self.max_carryover_batches_at_event_boundary,
            carryover,
        )

    def _release_completed_services(self, tick: int) -> None:
        for cell in sorted(self._cell_services):
            service = self._cell_services[cell]
            if service is None or service.finish_tick > tick:
                continue

            factory_id, hop_index = service.feeder
            path = self.factory_paths[factory_id]
            next_hop = hop_index + 1

            if next_hop == len(path):
                self._deliver(service.token, tick)
                self._cell_services[cell] = None
                continue

            downstream = (factory_id, next_hop)
            if self._queue_has_room(downstream):
                self._queues[downstream].append(service.token)
                self._cell_services[cell] = None
            else:
                self.blocked_after_service_ticks += 1

    def _deliver(self, token: NetworkToken, tick: int) -> None:
        self.delivered_states += 1
        remaining = self._batch_remaining[token.batch_id] - 1

        if remaining > 0:
            self._batch_remaining[token.batch_id] = remaining
            return

        del self._batch_remaining[token.batch_id]
        factory_id, generation_tick, token_count = self._batch_generation[
            token.batch_id
        ]
        self._delivered_batches.append(
            DeliveredBatch(
                batch_id=token.batch_id,
                factory_id=factory_id,
                generation_tick=generation_tick,
                completion_tick=tick,
                token_count=token_count,
            )
        )

    def _inject_pending_factory_outputs(
        self,
        *,
        tick: int,
        already_injected: dict[int, int],
    ) -> None:
        for factory_id in sorted(self._pending_factory):
            pending = self._pending_factory[factory_id]
            if pending is None:
                continue

            source = (factory_id, 0)
            remaining_bandwidth = (
                self.injection_bandwidth_states_per_tick
                - already_injected.get(factory_id, 0)
            )

            while (
                pending.tokens
                and remaining_bandwidth > 0
                and self._queue_has_room(source)
            ):
                self._queues[source].append(pending.tokens.popleft())
                remaining_bandwidth -= 1
                already_injected[factory_id] = (
                    already_injected.get(factory_id, 0) + 1
                )

            if not pending.tokens:
                self._pending_factory[factory_id] = None

    def _schedule_factory_event(
        self,
        *,
        tick: int,
        factory_id: int,
        states_per_batch: int,
        event_index: int,
    ) -> None:
        self.scheduled_factory_events += 1
        if factory_id not in self.factory_paths:
            raise BackpressureNetworkError(
                f"factory {factory_id} has no route."
            )
        if states_per_batch <= 0:
            raise BackpressureNetworkError(
                "states_per_batch must be > 0."
            )

        if self._pending_factory[factory_id] is not None:
            self.suppressed_factory_events += 1
            return

        batch_id = (
            f"F{factory_id}_E{event_index:08d}_T{tick:012d}"
        )
        tokens = deque(
            NetworkToken(
                batch_id=batch_id,
                factory_id=factory_id,
                token_index=token_index,
                generation_tick=tick,
            )
            for token_index in range(states_per_batch)
        )

        self._pending_factory[factory_id] = PendingFactoryBatch(
            batch_id=batch_id,
            factory_id=factory_id,
            generation_tick=tick,
            tokens=tokens,
        )
        self._batch_remaining[batch_id] = states_per_batch
        self._batch_generation[batch_id] = (
            factory_id,
            tick,
            states_per_batch,
        )
        self.generated_batches += 1
        self.generated_states += states_per_batch

    def _choose_feeder(self, cell: Cell) -> QueueKey | None:
        feeders = self._cell_feeders[cell]
        if not feeders:
            return None

        start = self._arbiter_pointer[cell] % len(feeders)
        for offset in range(len(feeders)):
            index = (start + offset) % len(feeders)
            key = feeders[index]
            if self._queues[key]:
                self._arbiter_pointer[cell] = (
                    index + 1
                ) % len(feeders)
                return key
        return None

    def _start_idle_cells(self, tick: int) -> None:
        for cell in sorted(self._cell_services):
            if self._cell_services[cell] is not None:
                continue

            feeder = self._choose_feeder(cell)
            if feeder is None:
                continue

            token = self._queues[feeder].popleft()
            self._cell_services[cell] = CellService(
                token=token,
                feeder=feeder,
                finish_tick=tick + self.hop_latency_ticks,
            )

    def _record_tick_metrics(self) -> None:
        injection_occupancies = [
            len(queue)
            for (factory_id, hop_index), queue in self._queues.items()
            if hop_index == 0
        ]
        intermediate_occupancies = [
            len(queue)
            for (factory_id, hop_index), queue in self._queues.items()
            if hop_index > 0
        ]

        self.max_injection_queue_occupancy = max(
            self.max_injection_queue_occupancy,
            max(injection_occupancies, default=0),
        )
        self.max_intermediate_queue_occupancy = max(
            self.max_intermediate_queue_occupancy,
            max(intermediate_occupancies, default=0),
        )

        if any(
            len(self._queues[key]) >= self._queue_capacity(key)
            for key in self._queues
            if key[1] == 0
        ):
            self.injection_queue_full_ticks += 1

        if any(
            len(self._queues[key]) >= self._queue_capacity(key)
            for key in self._queues
            if key[1] > 0
        ):
            self.intermediate_queue_full_ticks += 1

        pending_states = sum(
            len(pending.tokens)
            for pending in self._pending_factory.values()
            if pending is not None
        )
        if pending_states > 0:
            self.factory_output_backpressure_ticks += 1

        queued_states = sum(len(queue) for queue in self._queues.values())
        cell_states = sum(
            service is not None
            for service in self._cell_services.values()
        )
        self.max_network_states = max(
            self.max_network_states,
            pending_states + queued_states + cell_states,
        )

        for cell, service in self._cell_services.items():
            if service is not None:
                self._cell_busy_ticks[cell] += 1

    def step(
        self,
        *,
        tick: int,
        scheduled_factories: Iterable[tuple[int, int]],
        states_per_batch: int,
    ) -> None:
        """
        Advance one integer network tick.

        scheduled_factories contains (event_index, factory_id) pairs whose
        nominal factory completion occurs at this tick.
        """
        events = tuple(scheduled_factories)
        if events:
            self._record_event_boundary(tick)

        self._release_completed_services(tick)

        injected: dict[int, int] = {}
        self._inject_pending_factory_outputs(
            tick=tick,
            already_injected=injected,
        )

        for event_index, factory_id in events:
            self._schedule_factory_event(
                tick=tick,
                factory_id=factory_id,
                states_per_batch=states_per_batch,
                event_index=event_index,
            )

        self._inject_pending_factory_outputs(
            tick=tick,
            already_injected=injected,
        )
        self._start_idle_cells(tick)
        self._record_tick_metrics()

    def is_empty(self) -> bool:
        return (
            all(
                pending is None
                for pending in self._pending_factory.values()
            )
            and all(not queue for queue in self._queues.values())
            and all(
                service is None
                for service in self._cell_services.values()
            )
        )

    def run(
        self,
        *,
        event_schedule: dict[int, tuple[tuple[int, int], ...]],
        generation_horizon_end_tick: int,
        states_per_batch: int,
        max_drain_ticks: int,
    ) -> BackpressureTraceSummary:
        if generation_horizon_end_tick <= 0:
            raise BackpressureNetworkError(
                "generation_horizon_end_tick must be > 0."
            )
        if max_drain_ticks <= 0:
            raise BackpressureNetworkError(
                "max_drain_ticks must be > 0."
            )

        for tick in range(generation_horizon_end_tick):
            self.step(
                tick=tick,
                scheduled_factories=event_schedule.get(tick, ()),
                states_per_batch=states_per_batch,
            )

        generation_busy_ticks = dict(self._cell_busy_ticks)

        drain_tick = generation_horizon_end_tick
        drain_limit = generation_horizon_end_tick + max_drain_ticks

        while not self.is_empty() and drain_tick <= drain_limit:
            self.step(
                tick=drain_tick,
                scheduled_factories=(),
                states_per_batch=states_per_batch,
            )
            if self.is_empty():
                break
            drain_tick += 1

        if not self.is_empty():
            raise BackpressureNetworkError(
                "network did not drain within max_drain_ticks."
            )

        latencies = sorted(
            batch.latency_ticks
            for batch in self._delivered_batches
        )
        if latencies:
            index = max(
                0,
                min(
                    len(latencies) - 1,
                    math.ceil(0.95 * len(latencies)) - 1,
                ),
            )
            mean_latency = mean(latencies)
            p95_latency = latencies[index]
            max_latency = latencies[-1]
        else:
            mean_latency = 0.0
            p95_latency = 0
            max_latency = 0

        busiest = max(generation_busy_ticks.values(), default=0)
        generation_horizon_capacity = generation_horizon_end_tick

        return BackpressureTraceSummary(
            scheduled_factory_events=self.scheduled_factory_events,
            generated_batches=self.generated_batches,
            suppressed_factory_events=self.suppressed_factory_events,
            generated_states=self.generated_states,
            delivered_states=self.delivered_states,
            max_network_states=self.max_network_states,
            max_injection_queue_occupancy=(
                self.max_injection_queue_occupancy
            ),
            max_intermediate_queue_occupancy=(
                self.max_intermediate_queue_occupancy
            ),
            injection_queue_full_ticks=self.injection_queue_full_ticks,
            intermediate_queue_full_ticks=(
                self.intermediate_queue_full_ticks
            ),
            factory_output_backpressure_ticks=(
                self.factory_output_backpressure_ticks
            ),
            blocked_after_service_ticks=self.blocked_after_service_ticks,
            max_carryover_batches_at_event_boundary=(
                self.max_carryover_batches_at_event_boundary
            ),
            event_boundaries_with_carryover=(
                self.event_boundaries_with_carryover
            ),
            fraction_event_boundaries_with_carryover=(
                self.event_boundaries_with_carryover
                / self._event_boundary_count
                if self._event_boundary_count
                else 0.0
            ),
            mean_batch_latency_ticks=mean_latency,
            p95_batch_latency_ticks=p95_latency,
            max_batch_latency_ticks=max_latency,
            drain_tail_ticks=max(
                0,
                drain_tick - generation_horizon_end_tick,
            ),
            busiest_cell_busy_ticks=busiest,
            busiest_cell_utilization_during_generation_horizon=min(
                1.0,
                busiest / generation_horizon_capacity,
            ),
            total_cell_busy_ticks=sum(
                self._cell_busy_ticks.values()
            ),
            all_generated_states_delivered=(
                self.generated_states == self.delivered_states
            ),
        )
