from __future__ import annotations

from dataclasses import dataclass
import math


class PrefillPolicyError(ValueError):
    """Raised when a buffer-prefill policy is invalid."""


@dataclass(frozen=True)
class PrefillCost:
    requested_initial_states: int
    successful_batches_required: int
    expected_prefill_seconds: float
    std_prefill_seconds: float
    produced_states_on_required_successes: int
    discarded_states_from_final_prefill_batch: int


def requested_initial_states(
    *,
    buffer_capacity_states: int,
    fill_fraction: float,
) -> int:
    if buffer_capacity_states <= 0:
        raise PrefillPolicyError("buffer_capacity_states must be > 0.")
    if not 0 <= fill_fraction <= 1:
        raise PrefillPolicyError("fill_fraction must be in [0, 1].")

    # Configured benchmark capacities are divisible by four, so the standard
    # 0/25/50/75/100% policy grid maps exactly to integer states.
    requested = buffer_capacity_states * fill_fraction
    rounded = round(requested)
    if not math.isclose(requested, rounded, abs_tol=1e-12):
        raise PrefillPolicyError(
            "fill_fraction does not map to an integer number of states for "
            "this capacity."
        )
    return int(rounded)


def prefill_cost(
    *,
    requested_states: int,
    output_states_per_successful_batch: int,
    batch_success_probability: float,
    batch_duration_seconds: float,
) -> PrefillCost:
    """
    Expected pre-start latency for a requested initial buffer occupancy.

    Magic states arrive in protocol-sized successful batches. If the requested
    occupancy is not a multiple of the batch output, the final successful batch
    is partially retained and the remainder is explicitly counted as discarded.
    """
    if requested_states < 0:
        raise PrefillPolicyError("requested_states must be >= 0.")
    if output_states_per_successful_batch <= 0:
        raise PrefillPolicyError(
            "output_states_per_successful_batch must be > 0."
        )
    if not 0 < batch_success_probability <= 1:
        raise PrefillPolicyError(
            "batch_success_probability must be in the interval (0, 1]."
        )
    if batch_duration_seconds <= 0:
        raise PrefillPolicyError("batch_duration_seconds must be > 0.")

    if requested_states == 0:
        return PrefillCost(
            requested_initial_states=0,
            successful_batches_required=0,
            expected_prefill_seconds=0.0,
            std_prefill_seconds=0.0,
            produced_states_on_required_successes=0,
            discarded_states_from_final_prefill_batch=0,
        )

    successes = math.ceil(
        requested_states / output_states_per_successful_batch
    )
    probability = batch_success_probability

    mean_attempts = successes / probability
    failure_variance = successes * (1.0 - probability) / (probability**2)

    produced = successes * output_states_per_successful_batch
    discarded = produced - requested_states

    return PrefillCost(
        requested_initial_states=requested_states,
        successful_batches_required=successes,
        expected_prefill_seconds=mean_attempts * batch_duration_seconds,
        std_prefill_seconds=(
            math.sqrt(failure_variance) * batch_duration_seconds
        ),
        produced_states_on_required_successes=produced,
        discarded_states_from_final_prefill_batch=discarded,
    )
