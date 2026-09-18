import pytest

from experiments.static_resources import run
from metrics.physical_qubits import data_block_physical_qubits
from metrics.runtime import runtime_from_t_state_supply
from metrics.space_time_volume import space_time_volume


def test_data_block_physical_qubits_baseline_lower_bound():
    assert data_block_physical_qubits(
        logical_qubits=100,
        distance=21,
        physical_qubits_per_d2=2.0,
    ) == 88200


def test_supply_limited_runtime_baseline():
    runtime = runtime_from_t_state_supply(
        t_count=10_000_000,
        factories=138,
        effective_states_per_second_per_factory=60.47 / 3.0,
    )

    assert runtime == pytest.approx(3595.0273581581955, rel=1e-12)


def test_space_time_volume_baseline_lower_bound():
    stv = space_time_volume(
        physical_qubits=88200,
        runtime_seconds=3595.0273581581955,
    )

    assert stv == pytest.approx(317081412.98955286, rel=1e-12)


def test_static_resource_experiment_reports_lower_bound_scope():
    result = run("configs/baseline.yaml")

    assert result["scope"] == "data_block_only_lower_bound"
    assert result["code_distance"] == 21
    assert result["factories"] == 138
    assert result["physical_qubits"] == 88200
    assert result["runtime_seconds"] == pytest.approx(3595.0273581581955, rel=1e-12)
    assert result["space_time_volume_qubit_seconds"] == pytest.approx(
        317081412.98955286,
        rel=1e-12,
    )
