import math

import pytest

from experiments.buffer_risk_characterization import run
from simulator.buffer_risk import (
    analyze_buffer_risk,
    periodic_service_pattern,
)


def test_d25_consumer_service_pattern_is_exact_55_over_8():
    pattern = periodic_service_pattern(
        target_states=10_000_000,
        nominal_runtime_ns=3_600_000_000_000,
        batch_duration_ns=2_475_000,
    )

    assert pattern == (6, 7, 7, 7, 7, 7, 7, 7)
    assert sum(pattern) == 55


def test_small_buffer_survival_is_preserved_in_log_space():
    result = analyze_buffer_risk(
        target_states=10_000_000,
        nominal_runtime_ns=3_600_000_000_000,
        batch_duration_ns=2_475_000,
        output_states_per_successful_batch=12,
        batch_success_probability=0.89,
        capacity_states=24,
        initial_buffer_states=0,
    )

    # Linear probability underflows, but log-space survival remains informative.
    assert result.probability_no_starvation == 0.0
    assert result.log10_probability_no_starvation == pytest.approx(
        -891.7425007960173,
        abs=1e-9,
    )
    assert result.probability_any_starvation == 1.0


def test_exact_capacity_48_starvation_risk():
    result = analyze_buffer_risk(
        target_states=10_000_000,
        nominal_runtime_ns=3_600_000_000_000,
        batch_duration_ns=2_475_000,
        output_states_per_successful_batch=12,
        batch_success_probability=0.89,
        capacity_states=48,
        initial_buffer_states=0,
    )

    assert result.probability_no_starvation == pytest.approx(
        0.0703687011481,
        abs=1e-12,
    )
    assert result.probability_any_starvation == pytest.approx(
        0.9296312988519,
        abs=1e-12,
    )
    assert result.expected_starved_service_slots == pytest.approx(
        10.6239845613,
        abs=1e-9,
    )


def test_exact_capacity_96_risk_includes_d27_service_pattern():
    result = analyze_buffer_risk(
        target_states=10_000_000,
        nominal_runtime_ns=3_600_000_000_000,
        batch_duration_ns=2_673_000,
        output_states_per_successful_batch=12,
        batch_success_probability=0.89,
        capacity_states=96,
        initial_buffer_states=0,
    )

    assert result.service_period_batches == 40
    assert result.probability_any_starvation == pytest.approx(
        0.2397476187931,
        abs=1e-12,
    )
    assert result.expected_stall_intervals == pytest.approx(
        0.315448748306,
        abs=1e-9,
    )


def test_end_to_end_exact_buffer_risk_characterization():
    result = run("configs/litinski_buffer_risk_10mT.yaml")
    rows = {row["buffer_capacity_states"]: row for row in result["results"]}

    assert result["sampling_error"] == "none_within_model"
    assert list(rows) == [12, 24, 48, 96]

    assert rows[12]["code_distance"] == 25
    assert rows[24]["code_distance"] == 25
    assert rows[48]["code_distance"] == 25
    assert rows[96]["code_distance"] == 27

    assert rows[48]["probability_any_starvation"] == pytest.approx(
        0.9296312988519,
        abs=1e-12,
    )
    assert rows[96]["probability_any_starvation"] == pytest.approx(
        0.2397476187931,
        abs=1e-12,
    )

    assert rows[96]["physical_qubits"] == 438_858
    assert rows[96]["probability_any_starvation"] < rows[48][
        "probability_any_starvation"
    ]

    assert math.isfinite(rows[12]["log10_probability_no_starvation"])
    assert rows[12]["log10_probability_no_starvation"] < -70_000
