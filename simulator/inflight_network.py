from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import mean
from typing import Iterable


class InFlightNetworkError(ValueError):
    """Raised when persistent transport-network inputs are invalid."""


Cell = tuple[int, int]


@dataclass(frozen=True)
class TokenRecord:
    batch_id: str
    factory_id: int
    token_index: int
    generation_tick: int
    completion_tick: int
    contention_wait_ticks: int


@dataclass(frozen=True)
class BatchRecord:
    batch_id: str
    factory_id: int
    generation_tick: int
    completion_tick: int
    token_count: int
    max_token_contention_wait_ticks: int
    total_token_contention_wait_ticks: int

    @property
    def latency_ticks(self) -> int:
        return self.completion_tick - self.generation_tick


@dataclass(frozen=True)
class NetworkTraceSummary:
    event_count: int
    generated_batches: int
    generated_states: int
    max_carryover_batches_at_event_boundary: int
    event_boundaries_with_carryover: int
    fraction_event_boundaries_with_carryover: float
    inflight_batches_at_generation_horizon_end: int
    drain_tail_ticks: int
    mean_batch_latency_ticks: float
    p95_batch_latency_ticks: int
    max_batch_latency_ticks: int
    mean_contention_wait_ticks_per_state: float
    max_contention_wait_ticks_per_state: int
    busiest_cell_reserved_ticks: int
    busiest_cell_utilization_during_generation_horizon: float
    total_reserved_cell_ticks: int


class PersistentReservationNetwork:
    """
    Persistent absolute-time route reservation network.

    Unlike Milestone 14's event-local scheduler, reservations are never reset at
    a factory event. New batches see all already-reserved future cell-time slots,
    so transport can remain in flight across arbitrarily many later events.

    A token may wait between hops. Waiting nodes themselves have unbounded
    storage in this milestone; finite node-buffer capacity is a later refinement.
    """

    def __init__(
        self,
        *,
        factory_paths: dict[int, tuple[Cell, ...]],
        lane_capacity_states_per_tick: int,
        hop_latency_ticks: int,
    ) -> None:
        if not factory_paths:
            raise InFlightNetworkError("factory_paths must not be empty.")
        if any(not path for path in factory_paths.values()):
            raise InFlightNetworkError(
                "every factory path must contain at least one cell."
            )
        if lane_capacity_states_per_tick <= 0:
            raise InFlightNetworkError(
                "lane_capacity_states_per_tick must be > 0."
            )
        if hop_latency_ticks <= 0:
            raise InFlightNetworkError("hop_latency_ticks must be > 0.")

        self.factory_paths = {
            int(factory_id): tuple(path)
            for factory_id, path in factory_paths.items()
        }
        self.lane_capacity_states_per_tick = (
            lane_capacity_states_per_tick
        )
        self.hop_latency_ticks = hop_latency_ticks

        self._reservations: dict[tuple[Cell, int], int] = {}
        self._cell_reserved_ticks: dict[Cell, int] = {}
        self._batches: list[BatchRecord] = []
        self._tokens: list[TokenRecord] = []

    @property
    def batches(self) -> tuple[BatchRecord, ...]:
        return tuple(self._batches)

    @property
    def tokens(self) -> tuple[TokenRecord, ...]:
        return tuple(self._tokens)

    def _cell_interval_is_free(
        self,
        *,
        cell: Cell,
        start_tick: int,
    ) -> bool:
        for tick in range(
            start_tick,
            start_tick + self.hop_latency_ticks,
        ):
            if (
                self._reservations.get((cell, tick), 0)
                >= self.lane_capacity_states_per_tick
            ):
                return False
        return True

    def _reserve_cell_interval(
        self,
        *,
        cell: Cell,
        start_tick: int,
    ) -> None:
        for tick in range(
            start_tick,
            start_tick + self.hop_latency_ticks,
        ):
            key = (cell, tick)
            self._reservations[key] = self._reservations.get(key, 0) + 1
            self._cell_reserved_ticks[cell] = (
                self._cell_reserved_ticks.get(cell, 0) + 1
            )

    def _schedule_one_token(
        self,
        *,
        batch_id: str,
        factory_id: int,
        token_index: int,
        generation_tick: int,
    ) -> TokenRecord:
        if generation_tick < 0:
            raise InFlightNetworkError("generation_tick must be >= 0.")
        if factory_id not in self.factory_paths:
            raise InFlightNetworkError(
                f"factory {factory_id} has no configured route."
            )

        earliest = generation_tick
        contention_wait = 0

        for cell in self.factory_paths[factory_id]:
            start = earliest
            while not self._cell_interval_is_free(
                cell=cell,
                start_tick=start,
            ):
                start += 1

            contention_wait += start - earliest
            self._reserve_cell_interval(
                cell=cell,
                start_tick=start,
            )
            earliest = start + self.hop_latency_ticks

        return TokenRecord(
            batch_id=batch_id,
            factory_id=factory_id,
            token_index=token_index,
            generation_tick=generation_tick,
            completion_tick=earliest,
            contention_wait_ticks=contention_wait,
        )

    def enqueue_simultaneous_batches(
        self,
        *,
        generation_tick: int,
        batches: Iterable[tuple[str, int, int]],
    ) -> tuple[BatchRecord, ...]:
        """
        Enqueue batches generated at the same factory event.

        Each tuple is (batch_id, factory_id, state_count). Scheduling order is
        round-robin by token index and then factory ID, preventing an entire
        batch from receiving hidden priority merely because it was listed first.
        """
        specs = sorted(
            [
                (
                    str(batch_id),
                    int(factory_id),
                    int(state_count),
                )
                for batch_id, factory_id, state_count in batches
            ],
            key=lambda item: (item[1], item[0]),
        )
        if not specs:
            return ()
        if any(state_count <= 0 for _, _, state_count in specs):
            raise InFlightNetworkError("batch state_count must be > 0.")
        if len({batch_id for batch_id, _, _ in specs}) != len(specs):
            raise InFlightNetworkError("batch_id values must be unique.")
        existing_ids = {batch.batch_id for batch in self._batches}
        if any(batch_id in existing_ids for batch_id, _, _ in specs):
            raise InFlightNetworkError("batch_id already exists.")

        token_records: dict[str, list[TokenRecord]] = {
            batch_id: [] for batch_id, _, _ in specs
        }
        max_states = max(state_count for _, _, state_count in specs)

        for token_index in range(max_states):
            for batch_id, factory_id, state_count in specs:
                if token_index >= state_count:
                    continue
                token = self._schedule_one_token(
                    batch_id=batch_id,
                    factory_id=factory_id,
                    token_index=token_index,
                    generation_tick=generation_tick,
                )
                token_records[batch_id].append(token)
                self._tokens.append(token)

        by_id = {
            batch_id: (factory_id, state_count)
            for batch_id, factory_id, state_count in specs
        }
        records: list[BatchRecord] = []

        for batch_id, tokens in token_records.items():
            factory_id, state_count = by_id[batch_id]
            record = BatchRecord(
                batch_id=batch_id,
                factory_id=factory_id,
                generation_tick=generation_tick,
                completion_tick=max(
                    token.completion_tick for token in tokens
                ),
                token_count=state_count,
                max_token_contention_wait_ticks=max(
                    token.contention_wait_ticks for token in tokens
                ),
                total_token_contention_wait_ticks=sum(
                    token.contention_wait_ticks for token in tokens
                ),
            )
            self._batches.append(record)
            records.append(record)

        return tuple(
            sorted(
                records,
                key=lambda record: (
                    record.factory_id,
                    record.batch_id,
                ),
            )
        )

    def inflight_batches_at(self, tick: int) -> tuple[BatchRecord, ...]:
        if tick < 0:
            raise InFlightNetworkError("tick must be >= 0.")
        return tuple(
            batch
            for batch in self._batches
            if batch.generation_tick <= tick < batch.completion_tick
        )

    def completed_batches_by(self, tick: int) -> tuple[BatchRecord, ...]:
        if tick < 0:
            raise InFlightNetworkError("tick must be >= 0.")
        return tuple(
            batch
            for batch in self._batches
            if batch.completion_tick <= tick
        )

    def summarize(
        self,
        *,
        event_ticks: Iterable[int],
        generation_horizon_end_tick: int,
    ) -> NetworkTraceSummary:
        ticks = tuple(event_ticks)
        if not ticks:
            raise InFlightNetworkError("event_ticks must not be empty.")
        if generation_horizon_end_tick <= 0:
            raise InFlightNetworkError(
                "generation_horizon_end_tick must be > 0."
            )

        carryover_counts = [
            sum(
                batch.generation_tick < tick < batch.completion_tick
                for batch in self._batches
            )
            for tick in ticks
        ]
        latencies = sorted(
            batch.latency_ticks for batch in self._batches
        )
        waits = [
            token.contention_wait_ticks
            for token in self._tokens
        ]

        if not latencies:
            p95 = 0
            mean_latency = 0.0
            max_latency = 0
        else:
            index = max(
                0,
                min(
                    len(latencies) - 1,
                    math.ceil(0.95 * len(latencies)) - 1,
                ),
            )
            p95 = latencies[index]
            mean_latency = mean(latencies)
            max_latency = latencies[-1]

        max_completion = max(
            (batch.completion_tick for batch in self._batches),
            default=generation_horizon_end_tick,
        )
        final_inflight = len(
            self.inflight_batches_at(generation_horizon_end_tick)
        )
        busiest = max(
            self._cell_reserved_ticks.values(),
            default=0,
        )

        utilization = min(
            1.0,
            busiest
            / (
                generation_horizon_end_tick
                * self.lane_capacity_states_per_tick
            ),
        )

        return NetworkTraceSummary(
            event_count=len(ticks),
            generated_batches=len(self._batches),
            generated_states=len(self._tokens),
            max_carryover_batches_at_event_boundary=max(
                carryover_counts,
                default=0,
            ),
            event_boundaries_with_carryover=sum(
                count > 0 for count in carryover_counts
            ),
            fraction_event_boundaries_with_carryover=(
                sum(count > 0 for count in carryover_counts)
                / len(carryover_counts)
            ),
            inflight_batches_at_generation_horizon_end=final_inflight,
            drain_tail_ticks=max(
                0,
                max_completion - generation_horizon_end_tick,
            ),
            mean_batch_latency_ticks=mean_latency,
            p95_batch_latency_ticks=p95,
            max_batch_latency_ticks=max_latency,
            mean_contention_wait_ticks_per_state=(
                mean(waits) if waits else 0.0
            ),
            max_contention_wait_ticks_per_state=max(
                waits,
                default=0,
            ),
            busiest_cell_reserved_ticks=busiest,
            busiest_cell_utilization_during_generation_horizon=utilization,
            total_reserved_cell_ticks=sum(
                self._cell_reserved_ticks.values()
            ),
        )
