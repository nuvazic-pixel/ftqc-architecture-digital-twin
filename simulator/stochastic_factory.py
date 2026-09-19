from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Iterator

import numpy as np


class StochasticFactoryError(ValueError):
    """Raised when stochastic factory inputs are invalid."""


@dataclass(frozen=True)
class FactoryBatchEvent:
    batch_index: int
    time_seconds: float
    success: bool
    produced_states: int


@dataclass(frozen=True)
class CompletionTimeMoments:
    successful_batches_required: int
    batch_duration_seconds: float
    mean_attempted_batches: float
    mean_runtime_seconds: float
    std_runtime_seconds: float


def successful_batches_required(*, t_count: int, output_states_per_batch: int) -> int:
    if t_count < 0:
        raise StochasticFactoryError("t_count must be >= 0.")
    if output_states_per_batch <= 0:
        raise StochasticFactoryError("output_states_per_batch must be > 0.")
    if t_count == 0:
        return 0
    return math.ceil(t_count / output_states_per_batch)


def protocol_batch_duration_seconds(
    *,
    distance: int,
    protocol_steps_per_batch: float,
    code_cycle_time_seconds: float,
) -> float:
    if distance < 1 or distance % 2 == 0:
        raise StochasticFactoryError("distance must be a positive odd integer.")
    if protocol_steps_per_batch <= 0:
        raise StochasticFactoryError("protocol_steps_per_batch must be > 0.")
    if code_cycle_time_seconds <= 0:
        raise StochasticFactoryError("code_cycle_time_seconds must be > 0.")

    return distance * protocol_steps_per_batch * code_cycle_time_seconds


def single_factory_completion_time_moments(
    *,
    t_count: int,
    output_states_per_batch: int,
    batch_success_probability: float,
    batch_duration_seconds: float,
) -> CompletionTimeMoments:
    """
    Exact first two moments for independent Bernoulli batch success.

    The number of failed batches before n successful batches follows a negative
    binomial distribution. Runtime is total attempted batches multiplied by the
    fixed protocol batch duration.
    """
    if not 0 < batch_success_probability <= 1:
        raise StochasticFactoryError(
            "batch_success_probability must be in the interval (0, 1]."
        )
    if batch_duration_seconds <= 0:
        raise StochasticFactoryError("batch_duration_seconds must be > 0.")

    successes = successful_batches_required(
        t_count=t_count,
        output_states_per_batch=output_states_per_batch,
    )
    if successes == 0:
        return CompletionTimeMoments(
            successful_batches_required=0,
            batch_duration_seconds=batch_duration_seconds,
            mean_attempted_batches=0.0,
            mean_runtime_seconds=0.0,
            std_runtime_seconds=0.0,
        )

    p = batch_success_probability
    mean_attempts = successes / p
    failure_variance = successes * (1.0 - p) / (p**2)

    return CompletionTimeMoments(
        successful_batches_required=successes,
        batch_duration_seconds=batch_duration_seconds,
        mean_attempted_batches=mean_attempts,
        mean_runtime_seconds=mean_attempts * batch_duration_seconds,
        std_runtime_seconds=math.sqrt(failure_variance) * batch_duration_seconds,
    )


def simulate_single_factory_completion_times(
    *,
    t_count: int,
    output_states_per_batch: int,
    batch_success_probability: float,
    batch_duration_seconds: float,
    runs: int,
    seed: int,
) -> np.ndarray:
    """
    Vectorized Monte Carlo completion times for exactly one factory.

    NumPy's negative-binomial sampler draws the number of failed batches before
    the required number of successful batches. This preserves the bursty
    all-or-nothing batch behavior without simulating ~1 million Bernoulli draws
    one by one for every Monte Carlo run.
    """
    if runs <= 0:
        raise StochasticFactoryError("runs must be > 0.")

    moments = single_factory_completion_time_moments(
        t_count=t_count,
        output_states_per_batch=output_states_per_batch,
        batch_success_probability=batch_success_probability,
        batch_duration_seconds=batch_duration_seconds,
    )
    successes = moments.successful_batches_required
    if successes == 0:
        return np.zeros(runs, dtype=float)

    rng = np.random.default_rng(seed)
    failures = rng.negative_binomial(
        successes,
        batch_success_probability,
        size=runs,
    )
    attempted_batches = successes + failures
    return attempted_batches.astype(float) * batch_duration_seconds


def summarize_completion_times(
    completion_times_seconds: np.ndarray,
    *,
    deadline_seconds: float | None = None,
) -> dict[str, float | int | None]:
    values = np.asarray(completion_times_seconds, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise StochasticFactoryError(
            "completion_times_seconds must be a non-empty 1D array."
        )
    if np.any(values < 0):
        raise StochasticFactoryError("completion times must be >= 0.")

    summary: dict[str, float | int | None] = {
        "runs": int(values.size),
        "mean_seconds": float(np.mean(values)),
        "std_seconds": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
        "p05_seconds": float(np.quantile(values, 0.05)),
        "p50_seconds": float(np.quantile(values, 0.50)),
        "p95_seconds": float(np.quantile(values, 0.95)),
        "p99_seconds": float(np.quantile(values, 0.99)),
        "min_seconds": float(np.min(values)),
        "max_seconds": float(np.max(values)),
        "observed_deadline_misses": None,
        "observed_deadline_miss_rate": None,
        "zero_miss_rule_of_three_upper_95": None,
    }

    if deadline_seconds is not None:
        if deadline_seconds <= 0:
            raise StochasticFactoryError("deadline_seconds must be > 0.")
        misses = int(np.count_nonzero(values > deadline_seconds))
        miss_rate = misses / values.size
        summary["observed_deadline_misses"] = misses
        summary["observed_deadline_miss_rate"] = float(miss_rate)
        if misses == 0:
            summary["zero_miss_rule_of_three_upper_95"] = float(3.0 / values.size)

    return summary


def iter_batch_events(
    *,
    output_states_per_batch: int,
    batch_success_probability: float,
    batch_duration_seconds: float,
    seed: int,
) -> Iterator[FactoryBatchEvent]:
    """
    Infinite deterministic-seed event stream for future buffer/consumer models.
    """
    if output_states_per_batch <= 0:
        raise StochasticFactoryError("output_states_per_batch must be > 0.")
    if not 0 < batch_success_probability <= 1:
        raise StochasticFactoryError(
            "batch_success_probability must be in the interval (0, 1]."
        )
    if batch_duration_seconds <= 0:
        raise StochasticFactoryError("batch_duration_seconds must be > 0.")

    rng = random.Random(seed)
    batch_index = 0
    while True:
        batch_index += 1
        success = rng.random() < batch_success_probability
        yield FactoryBatchEvent(
            batch_index=batch_index,
            time_seconds=batch_index * batch_duration_seconds,
            success=success,
            produced_states=output_states_per_batch if success else 0,
        )
