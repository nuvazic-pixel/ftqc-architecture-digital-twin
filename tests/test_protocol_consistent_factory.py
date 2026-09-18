import pytest

from experiments.litinski_minimal_setup import run
from simulator.protocol_factory import (
    expected_time_steps_per_good_state,
    protocol_factory_throughput,
)
from simulator.system_reliability import (
    logical_failure_budget_estimate,
    required_distance_for_computation,
)


def test_litinski_expected_time_steps_per_good_state():
    steps = expected_time_steps_per_good_state(
        output_states_per_batch=12,
        protocol_steps_per_batch=99,
        batch_success_probability=0.89,
    )

    assert steps == pytest.approx(9.269662921348315, rel=1e-12)


def test_whole_computation_reliability_selects_d25_for_10m_t_states():
    total_time_steps = 10_000_000 * (99 / (12 * 0.89))

    d = required_distance_for_computation(
        tile_count=210,
        total_time_steps=total_time_steps,
        physical_error=1.0e-3,
        physical_error_threshold=1.0e-2,
        fit_A=0.1,
        max_total_failure_probability=0.01,
        allowed_distances=[13, 15, 17, 19, 21, 23, 25, 27, 29, 31],
    )

    fail_d23 = logical_failure_budget_estimate(
        tile_count=210,
        total_time_steps=total_time_steps,
        distance=23,
        physical_error=1.0e-3,
        physical_error_threshold=1.0e-2,
        fit_A=0.1,
    )
    fail_d25 = logical_failure_budget_estimate(
        tile_count=210,
        total_time_steps=total_time_steps,
        distance=25,
        physical_error=1.0e-3,
        physical_error_threshold=1.0e-2,
        fit_A=0.1,
    )

    assert d == 25
    assert fail_d23 > 0.01
    assert fail_d25 < 0.01


def test_protocol_throughput_at_d25_with_one_microsecond_cycle():
    rate = protocol_factory_throughput(
        distance=25,
        code_cycle_time_seconds=1.0e-6,
        output_states_per_batch=12,
        protocol_steps_per_batch=99,
        batch_success_probability=0.89,
    )

    assert rate == pytest.approx(4315.151515151515, rel=1e-12)


def test_protocol_consistent_end_to_end_benchmark():
    result = run("configs/litinski_minimal_10mT.yaml")

    assert result["throughput_binding_status"] == "protocol_derived"
    assert result["routing_workspace_status"] == "embedded_in_named_layout"
    assert result["code_distance"] == 25
    assert result["total_tiles"] == 210
    assert result["physical_qubits"] == 262_500
    assert result["minimum_factories_for_runtime_at_selected_d"] == 1
    assert result["states_per_second_per_factory"] == pytest.approx(
        4315.151515151515,
        rel=1e-12,
    )
    assert result["runtime_seconds"] == pytest.approx(
        2317.415730337079,
        rel=1e-12,
    )
    assert result["estimated_total_logical_failure"] == pytest.approx(
        0.00486657303370787,
        rel=1e-12,
    )
    assert result["space_time_volume_qubit_seconds"] == pytest.approx(
        608321629.2134832,
        rel=1e-12,
    )
