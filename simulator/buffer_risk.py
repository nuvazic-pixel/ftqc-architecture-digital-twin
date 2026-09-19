from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


class BufferRiskError(ValueError):
    """Raised when exact buffer-risk inputs are invalid."""


@dataclass(frozen=True)
class ServiceSchedule:
    pattern: tuple[int, ...]
    batches_in_horizon: int
    full_periods_before_final: int
    remainder_before_final: tuple[int, ...]
    final_service_slots: int
    quantized_nominal_completion_seconds: float


@dataclass(frozen=True)
class BufferRiskResult:
    probability_no_starvation: float
    log10_probability_no_starvation: float
    probability_any_starvation: float
    expected_starved_service_slots: float
    expected_stall_intervals: float
    expected_overflow_states: float
    mean_buffer_states_after_service: float
    service_period_batches: int
    batches_in_horizon: int
    final_service_slots: int
    quantized_nominal_completion_seconds: float


def periodic_service_pattern(
    *,
    target_states: int,
    nominal_runtime_ns: int,
    batch_duration_ns: int,
    max_period_batches: int = 10000,
) -> tuple[int, ...]:
    """
    Return the exact repeating consumer-service pattern.

    The service rate is target_states / nominal_runtime. Integer arithmetic and
    gcd reduction expose the exact periodic 6/7/... slot pattern without
    floating-point drift.
    """
    if target_states <= 0:
        raise BufferRiskError("target_states must be > 0.")
    if nominal_runtime_ns <= 0:
        raise BufferRiskError("nominal_runtime_ns must be > 0.")
    if batch_duration_ns <= 0:
        raise BufferRiskError("batch_duration_ns must be > 0.")

    numerator = target_states * batch_duration_ns
    denominator = nominal_runtime_ns
    divisor = math.gcd(numerator, denominator)
    increment = numerator // divisor
    period = denominator // divisor

    if period > max_period_batches:
        raise BufferRiskError(
            "Exact service period exceeds max_period_batches; choose a larger "
            "limit or use an alternate scheduler representation."
        )

    accumulator = 0
    pattern: list[int] = []
    for _ in range(period):
        accumulator += increment
        slots, accumulator = divmod(accumulator, period)
        pattern.append(slots)

    if accumulator != 0:
        raise BufferRiskError("Internal service-period construction error.")

    return tuple(pattern)


def build_service_schedule(
    *,
    target_states: int,
    nominal_runtime_ns: int,
    batch_duration_ns: int,
) -> ServiceSchedule:
    pattern = periodic_service_pattern(
        target_states=target_states,
        nominal_runtime_ns=nominal_runtime_ns,
        batch_duration_ns=batch_duration_ns,
    )
    batches = (nominal_runtime_ns + batch_duration_ns - 1) // batch_duration_ns
    if batches < 1:
        raise BufferRiskError("Nominal horizon must contain at least one batch.")

    before_final = batches - 1
    periods, remainder_count = divmod(before_final, len(pattern))
    remainder = pattern[:remainder_count]

    served_before_final = periods * sum(pattern) + sum(remainder)
    final_slots = target_states - served_before_final
    if final_slots <= 0:
        raise BufferRiskError(
            "Target is reached before the final quantized batch; schedule model "
            "needs a shorter horizon."
        )

    return ServiceSchedule(
        pattern=pattern,
        batches_in_horizon=batches,
        full_periods_before_final=periods,
        remainder_before_final=remainder,
        final_service_slots=final_slots,
        quantized_nominal_completion_seconds=(
            batches * batch_duration_ns / 1_000_000_000
        ),
    )


def _step_matrices(
    *,
    capacity_states: int,
    service_slots: int,
    output_states_per_successful_batch: int,
    batch_success_probability: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Construct one-step matrices.

    Returns:
      P: full stochastic buffer-state transition matrix
      Q: substochastic transition matrix retaining only no-starvation paths
      A: augmented matrix accumulating exact expected rewards:
         missed slots, stall intervals, overflow states, post-service occupancy
    """
    if capacity_states <= 0:
        raise BufferRiskError("capacity_states must be > 0.")
    if service_slots < 0:
        raise BufferRiskError("service_slots must be >= 0.")
    if output_states_per_successful_batch <= 0:
        raise BufferRiskError(
            "output_states_per_successful_batch must be > 0."
        )
    if not 0 < batch_success_probability <= 1:
        raise BufferRiskError(
            "batch_success_probability must be in the interval (0, 1]."
        )

    states = capacity_states + 1
    P = np.zeros((states, states), dtype=float)
    Q = np.zeros((states, states), dtype=float)
    rewards = np.zeros((states, 4), dtype=float)

    branches = (
        (1.0 - batch_success_probability, 0),
        (batch_success_probability, output_states_per_successful_batch),
    )

    for buffer_before in range(states):
        for probability, produced in branches:
            raw_available = buffer_before + produced
            overflow = max(0, raw_available - capacity_states)
            available = min(capacity_states, raw_available)

            served = min(available, service_slots)
            missed = service_slots - served
            buffer_after = available - served

            P[buffer_before, buffer_after] += probability
            rewards[buffer_before, 0] += probability * missed
            rewards[buffer_before, 1] += probability * (1 if missed > 0 else 0)
            rewards[buffer_before, 2] += probability * overflow
            rewards[buffer_before, 3] += probability * buffer_after

            if missed == 0:
                Q[buffer_before, buffer_after] += probability

    reward_count = rewards.shape[1]
    augmented = np.zeros(
        (states + reward_count, states + reward_count),
        dtype=float,
    )
    augmented[:states, :states] = P
    augmented[:states, states:] = rewards
    augmented[states:, states:] = np.eye(reward_count)

    return P, Q, augmented


def _compose(matrices: list[np.ndarray]) -> np.ndarray:
    if not matrices:
        raise BufferRiskError("At least one matrix is required.")
    result = np.eye(matrices[0].shape[0])
    for matrix in matrices:
        result = result @ matrix
    return result


def _apply_matrix_power_scaled(
    vector: np.ndarray,
    matrix: np.ndarray,
    exponent: int,
) -> tuple[np.ndarray, float]:
    """
    Apply vector @ matrix**exponent while preserving tiny survival probability.

    The returned vector is normalized to sum to one. log_scale is the natural
    logarithm of the probability mass removed by normalization.
    """
    if exponent < 0:
        raise BufferRiskError("exponent must be >= 0.")

    mass = float(np.sum(vector))
    if mass <= 0:
        return np.zeros_like(vector), -math.inf

    accumulator = vector / mass
    log_scale = math.log(mass)

    if exponent == 0:
        return accumulator, log_scale

    base = matrix.copy()
    base_max = float(np.max(base))
    if base_max <= 0:
        return np.zeros_like(vector), -math.inf

    base /= base_max
    base_log_scale = math.log(base_max)
    remaining = exponent

    while remaining:
        if remaining & 1:
            updated = accumulator @ base
            updated_mass = float(np.sum(updated))
            if updated_mass <= 0:
                return np.zeros_like(vector), -math.inf
            accumulator = updated / updated_mass
            log_scale += base_log_scale + math.log(updated_mass)

        remaining >>= 1
        if remaining == 0:
            break

        squared = base @ base
        squared_max = float(np.max(squared))
        if squared_max <= 0:
            return np.zeros_like(vector), -math.inf

        base = squared / squared_max
        base_log_scale = 2.0 * base_log_scale + math.log(squared_max)

    return accumulator, log_scale


def analyze_buffer_risk(
    *,
    target_states: int,
    nominal_runtime_ns: int,
    batch_duration_ns: int,
    output_states_per_successful_batch: int,
    batch_success_probability: float,
    capacity_states: int,
    initial_buffer_states: int = 0,
) -> BufferRiskResult:
    """
    Exact finite-state characterization of starvation risk over the nominal run.

    For this bounded single-factory model, the result contains no Monte Carlo
    sampling error. Probability of any starvation is the probability that at
    least one scheduled consumer service slot cannot be filled by the
    quantized nominal completion time.
    """
    if not 0 <= initial_buffer_states <= capacity_states:
        raise BufferRiskError(
            "initial_buffer_states must be between 0 and capacity_states."
        )

    schedule = build_service_schedule(
        target_states=target_states,
        nominal_runtime_ns=nominal_runtime_ns,
        batch_duration_ns=batch_duration_ns,
    )

    step_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def matrices(service_slots: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if service_slots not in step_cache:
            step_cache[service_slots] = _step_matrices(
                capacity_states=capacity_states,
                service_slots=service_slots,
                output_states_per_successful_batch=(
                    output_states_per_successful_batch
                ),
                batch_success_probability=batch_success_probability,
            )
        return step_cache[service_slots]

    period_augmented = _compose(
        [matrices(slots)[2] for slots in schedule.pattern]
    )

    full_transform = np.linalg.matrix_power(
        period_augmented,
        schedule.full_periods_before_final,
    )
    for slots in schedule.remainder_before_final:
        full_transform = full_transform @ matrices(slots)[2]
    full_transform = full_transform @ matrices(schedule.final_service_slots)[2]

    state_count = capacity_states + 1
    reward_count = 4
    initial_augmented = np.zeros(state_count + reward_count, dtype=float)
    initial_augmented[initial_buffer_states] = 1.0
    final_augmented = initial_augmented @ full_transform
    rewards = final_augmented[state_count:]

    no_starvation_period = _compose(
        [matrices(slots)[1] for slots in schedule.pattern]
    )
    survival = np.zeros(state_count, dtype=float)
    survival[initial_buffer_states] = 1.0
    survival, log_survival = _apply_matrix_power_scaled(
        survival,
        no_starvation_period,
        schedule.full_periods_before_final,
    )

    for slots in (
        *schedule.remainder_before_final,
        schedule.final_service_slots,
    ):
        survival = survival @ matrices(slots)[1]
        mass = float(np.sum(survival))
        if mass <= 0:
            log_survival = -math.inf
            survival = np.zeros_like(survival)
            break
        survival /= mass
        log_survival += math.log(mass)

    if math.isinf(log_survival) and log_survival < 0:
        probability_no_starvation = 0.0
        log10_probability_no_starvation = -math.inf
        probability_any_starvation = 1.0
    else:
        probability_no_starvation = (
            math.exp(log_survival) if log_survival > -745 else 0.0
        )
        log10_probability_no_starvation = log_survival / math.log(10.0)
        probability_any_starvation = -math.expm1(log_survival)

    return BufferRiskResult(
        probability_no_starvation=probability_no_starvation,
        log10_probability_no_starvation=log10_probability_no_starvation,
        probability_any_starvation=probability_any_starvation,
        expected_starved_service_slots=float(rewards[0]),
        expected_stall_intervals=float(rewards[1]),
        expected_overflow_states=float(rewards[2]),
        mean_buffer_states_after_service=(
            float(rewards[3]) / schedule.batches_in_horizon
        ),
        service_period_batches=len(schedule.pattern),
        batches_in_horizon=schedule.batches_in_horizon,
        final_service_slots=schedule.final_service_slots,
        quantized_nominal_completion_seconds=(
            schedule.quantized_nominal_completion_seconds
        ),
    )
