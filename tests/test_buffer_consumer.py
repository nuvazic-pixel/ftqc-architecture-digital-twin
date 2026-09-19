import pytest

from experiments.buffer_sensitivity import run
from simulator.buffer_consumer import (
    replicated_storage_tiles,
    simulate_buffered_consumer,
)
from simulator.system_reliability import required_distance_for_runtime_budget


def test_integer_service_scheduler_has_no_floating_point_drift():
    result = simulate_buffered_consumer(
        target_states=100,
        nominal_runtime_seconds=10.0,
        batch_duration_ns=250_000_000,
        output_states_per_successful_batch=10,
        batch_success_probability=1.0,
        buffer_capacity_states=100,
        initial_buffer_states=100,
        seed=42,
    )

    assert result.completion_time_seconds == 10.0
    assert result.quantized_nominal_completion_seconds == 10.0
    assert result.starvation_extension_seconds == 0.0
    assert result.starved_service_slots == 0


def test_linear_storage_replication_is_explicit_and_monotonic():
    assert replicated_storage_tiles(
        buffer_capacity_states=12,
        base_capacity_states=12,
        base_storage_tiles=13,
    ) == 13
    assert replicated_storage_tiles(
        buffer_capacity_states=24,
        base_capacity_states=12,
        base_storage_tiles=13,
    ) == 26
    assert replicated_storage_tiles(
        buffer_capacity_states=48,
        base_capacity_states=12,
        base_storage_tiles=13,
    ) == 52


def test_larger_buffer_can_force_distance_jump_via_reliability_budget():
    common = dict(
        runtime_budget_seconds=3600,
        code_cycle_time_seconds=1e-6,
        physical_error=1e-3,
        physical_error_threshold=1e-2,
        fit_A=0.1,
        max_total_failure_probability=0.01,
        allowed_distances=[13, 15, 17, 19, 21, 23, 25, 27, 29, 31],
    )

    assert required_distance_for_runtime_budget(
        tile_count=210,
        **common,
    ) == 25
    assert required_distance_for_runtime_budget(
        tile_count=301,
        **common,
    ) == 27


def test_buffer_sensitivity_end_to_end():
    result = run("configs/litinski_buffer_10mT.yaml")
    rows = {row["buffer_capacity_states"]: row for row in result["results"]}

    assert list(rows) == [12, 24, 48, 96]

    assert rows[12]["code_distance"] == 25
    assert rows[24]["code_distance"] == 25
    assert rows[48]["code_distance"] == 25
    assert rows[96]["code_distance"] == 27

    assert rows[12]["physical_qubits"] == 262_500
    assert rows[24]["physical_qubits"] == 278_750
    assert rows[48]["physical_qubits"] == 311_250
    assert rows[96]["physical_qubits"] == 438_858

    assert rows[12]["starvation_extension_seconds"] > 100
    assert 1 < rows[24]["starvation_extension_seconds"] < 10
    assert rows[48]["starvation_extension_seconds"] == pytest.approx(0.002475)
    assert rows[96]["starvation_extension_seconds"] == 0.0

    assert rows[12]["starved_service_slots"] > rows[24]["starved_service_slots"]
    assert rows[24]["starved_service_slots"] > rows[48]["starved_service_slots"]
    assert rows[48]["starved_service_slots"] > rows[96]["starved_service_slots"]

    assert all(row["post_simulation_reliability_ok"] for row in rows.values())
