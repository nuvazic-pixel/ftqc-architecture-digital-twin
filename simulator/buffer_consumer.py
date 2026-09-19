from __future__ import annotations

from dataclasses import dataclass
import math
import random


class BufferConsumerError(ValueError):
    """Raised when buffer/consumer simulation inputs are invalid."""


@dataclass(frozen=True)
class BufferConsumerResult:
    buffer_capacity_states: int
    batch_duration_ns: int
    batches_executed: int
    completion_time_seconds: float
    quantized_nominal_completion_seconds: float
    starvation_extension_seconds: float
    raw_deadline_slip_seconds: float
    consumer_stall_intervals: int
    starved_service_slots: int
    produced_states: int
    served_states: int
    overflow_states: int
    final_buffer_states: int
    max_buffer_states: int
    mean_buffer_states: float


def replicated_storage_tiles(
    *,
    buffer_capacity_states: int,
    base_capacity_states: int,
    base_storage_tiles: int,
) -> int:
    """
    Linear storage-block replication sensitivity model.

    This is an explicit model assumption, not a claim that larger storage can
    be laid out with no extra routing/workspace cost.
    """
    if buffer_capacity_states <= 0:
        raise BufferConsumerError("buffer_capacity_states must be > 0.")
    if base_capacity_states <= 0:
        raise BufferConsumerError("base_capacity_states must be > 0.")
    if base_storage_tiles <= 0:
        raise BufferConsumerError("base_storage_tiles must be > 0.")

    blocks = math.ceil(buffer_capacity_states / base_capacity_states)
    return blocks * base_storage_tiles


def simulate_buffered_consumer(
    *,
    target_states: int,
    nominal_runtime_seconds: float,
    batch_duration_ns: int,
    output_states_per_successful_batch: int,
    batch_success_probability: float,
    buffer_capacity_states: int,
    initial_buffer_states: int,
    seed: int,
    max_runtime_multiplier: float = 10.0,
) -> BufferConsumerResult:
    """
    Simulate a bounded magic-state buffer feeding a fixed-rate consumer.

    Event order per batch:
      1. the factory batch succeeds or fails;
      2. produced states enter the bounded buffer (overflow is discarded);
      3. the consumer receives only the service slots available in this interval.

    Missed consumer service slots are *not* carried forward. This models a
    consumer with a fixed maximum issue rate: starvation causes real completion
    delay rather than being recovered by unbounded catch-up.

    Consumer scheduling uses integer nanoseconds and an integer accumulator, so
    no floating-point drift can change the 6/7/... service-slot pattern.
    """
    if target_states <= 0:
        raise BufferConsumerError("target_states must be > 0.")
    if nominal_runtime_seconds <= 0:
        raise BufferConsumerError("nominal_runtime_seconds must be > 0.")
    if batch_duration_ns <= 0:
        raise BufferConsumerError("batch_duration_ns must be > 0.")
    if output_states_per_successful_batch <= 0:
        raise BufferConsumerError(
            "output_states_per_successful_batch must be > 0."
        )
    if not 0 < batch_success_probability <= 1:
        raise BufferConsumerError(
            "batch_success_probability must be in the interval (0, 1]."
        )
    if buffer_capacity_states <= 0:
        raise BufferConsumerError("buffer_capacity_states must be > 0.")
    if not 0 <= initial_buffer_states <= buffer_capacity_states:
        raise BufferConsumerError(
            "initial_buffer_states must be between 0 and buffer capacity."
        )
    if max_runtime_multiplier <= 1:
        raise BufferConsumerError("max_runtime_multiplier must be > 1.")

    nominal_runtime_ns = int(round(nominal_runtime_seconds * 1_000_000_000))
    service_numerator_increment = target_states * batch_duration_ns
    service_denominator = nominal_runtime_ns
    service_accumulator = 0

    rng = random.Random(seed)
    buffer_states = initial_buffer_states
    served_states = 0
    produced_states = 0
    overflow_states = 0
    starved_service_slots = 0
    stall_intervals = 0
    batch_index = 0
    max_buffer_states = buffer_states
    buffer_sum = 0

    max_batches = math.ceil(
        max_runtime_multiplier * nominal_runtime_ns / batch_duration_ns
    )

    while served_states < target_states:
        batch_index += 1
        if batch_index > max_batches:
            raise BufferConsumerError(
                "Simulation exceeded max_runtime_multiplier before completion."
            )

        success = rng.random() < batch_success_probability
        produced = output_states_per_successful_batch if success else 0
        produced_states += produced

        room = buffer_capacity_states - buffer_states
        accepted = min(room, produced)
        buffer_states += accepted
        overflow_states += produced - accepted

        service_accumulator += service_numerator_increment
        service_slots, service_accumulator = divmod(
            service_accumulator,
            service_denominator,
        )
        service_slots = min(service_slots, target_states - served_states)

        served_now = min(buffer_states, service_slots)
        buffer_states -= served_now
        served_states += served_now

        missed = service_slots - served_now
        if missed > 0:
            starved_service_slots += missed
            stall_intervals += 1

        max_buffer_states = max(max_buffer_states, buffer_states)
        buffer_sum += buffer_states

    completion_ns = batch_index * batch_duration_ns
    quantized_batches = (
        nominal_runtime_ns + batch_duration_ns - 1
    ) // batch_duration_ns
    quantized_nominal_ns = quantized_batches * batch_duration_ns

    return BufferConsumerResult(
        buffer_capacity_states=buffer_capacity_states,
        batch_duration_ns=batch_duration_ns,
        batches_executed=batch_index,
        completion_time_seconds=completion_ns / 1_000_000_000,
        quantized_nominal_completion_seconds=(
            quantized_nominal_ns / 1_000_000_000
        ),
        starvation_extension_seconds=max(
            0.0,
            (completion_ns - quantized_nominal_ns) / 1_000_000_000,
        ),
        raw_deadline_slip_seconds=max(
            0.0,
            (completion_ns - nominal_runtime_ns) / 1_000_000_000,
        ),
        consumer_stall_intervals=stall_intervals,
        starved_service_slots=starved_service_slots,
        produced_states=produced_states,
        served_states=served_states,
        overflow_states=overflow_states,
        final_buffer_states=buffer_states,
        max_buffer_states=max_buffer_states,
        mean_buffer_states=buffer_sum / batch_index,
    )
