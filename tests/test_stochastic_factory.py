import itertools

import numpy as np
import pytest

from experiments.stochastic_factory_runtime import run
from simulator.stochastic_factory import (
    iter_batch_events,
    protocol_batch_duration_seconds,
    simulate_single_factory_completion_times,
    single_factory_completion_time_moments,
    successful_batches_required,
)


def test_successful_batches_required_preserves_batch_quantization():
    assert successful_batches_required(
        t_count=10_000_000,
        output_states_per_batch=12,
    ) == 833_334


def test_analytical_completion_time_moments_for_litinski_10mT():
    duration = protocol_batch_duration_seconds(
        distance=25,
        protocol_steps_per_batch=99,
        code_cycle_time_seconds=1.0e-6,
    )
    moments = single_factory_completion_time_moments(
        t_count=10_000_000,
        output_states_per_batch=12,
        batch_success_probability=0.89,
        batch_duration_seconds=duration,
    )

    assert duration == pytest.approx(0.002475, rel=1e-12)
    assert moments.successful_batches_required == 833_334
    assert moments.mean_runtime_seconds == pytest.approx(
        2317.417584269663,
        rel=1e-12,
    )
    assert moments.std_runtime_seconds == pytest.approx(
        0.8419592835690496,
        rel=1e-12,
    )


def test_monte_carlo_is_seed_reproducible():
    kwargs = dict(
        t_count=1200,
        output_states_per_batch=12,
        batch_success_probability=0.89,
        batch_duration_seconds=0.002475,
        runs=100,
        seed=42,
    )
    first = simulate_single_factory_completion_times(**kwargs)
    second = simulate_single_factory_completion_times(**kwargs)

    assert np.array_equal(first, second)


def test_event_stream_is_bursty_not_fractional():
    events = list(
        itertools.islice(
            iter_batch_events(
                output_states_per_batch=12,
                batch_success_probability=0.89,
                batch_duration_seconds=0.002475,
                seed=42,
            ),
            100,
        )
    )

    produced = {event.produced_states for event in events}
    assert produced.issubset({0, 12})
    assert 0 in produced
    assert 12 in produced


def test_stochastic_end_to_end_benchmark():
    result = run("configs/litinski_stochastic_10mT.yaml")
    mc = result["monte_carlo"]

    assert result["code_distance"] == 25
    assert result["factories"] == 1
    assert result["successful_batches_required"] == 833_334
    assert result["physical_qubits"] == 262_500
    assert result["multi_factory_supported"] is False

    # Monte Carlo mean should agree tightly with the exact negative-binomial mean.
    assert mc["mean_seconds"] == pytest.approx(
        result["analytical_mean_runtime_seconds"],
        abs=0.02,
    )
    assert mc["std_seconds"] == pytest.approx(
        result["analytical_std_runtime_seconds"],
        abs=0.02,
    )

    # No 1-hour misses were observed in this seeded 10k-run experiment.
    assert mc["observed_deadline_misses"] == 0
    assert mc["observed_deadline_miss_rate"] == 0.0
    assert mc["zero_miss_rule_of_three_upper_95"] == pytest.approx(0.0003)

    # Discrete batches introduce a tiny final-batch overhead over the continuous
    # expected-rate calculation; it must be positive and less than one batch.
    assert 0 < result["final_batch_quantization_overhead_seconds"] < result[
        "batch_duration_seconds"
    ]
