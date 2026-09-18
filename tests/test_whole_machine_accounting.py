import pytest

from experiments.whole_machine_accounting import run
from metrics.factory_footprint import factory_distillation_term
from metrics.resource_accounting import ResourceTerm, aggregate_resource_terms


def test_litinski_116_to_12_factory_footprint_at_d21():
    term = factory_distillation_term(
        factories=1,
        distance=21,
        distillation_tiles_per_factory=44,
        physical_qubits_per_d2=2.0,
        source="literature",
        model="litinski_116_to_12_compact",
    )

    assert term.value == 38808


def test_missing_required_term_is_not_silently_zero():
    result = aggregate_resource_terms(
        (
            ResourceTerm("known", 100, "test", "test", "high"),
            ResourceTerm("missing", None, "unmodeled", "unmodeled", "unknown"),
        )
    )

    assert result.known_subtotal == 100
    assert result.total_physical_qubits is None
    assert result.complete is False
    assert result.missing_terms == ("missing",)


def test_factory_sensitivity_does_not_change_data_term():
    data = ResourceTerm(
        "data_block_qubits",
        88200,
        "model_assumption",
        "logical_patch_lower_bound",
        "lower_bound",
    )
    f44 = factory_distillation_term(
        factories=138,
        distance=21,
        distillation_tiles_per_factory=44,
        physical_qubits_per_d2=2.0,
        source="literature",
        model="litinski_116_to_12_compact",
    )
    f88 = factory_distillation_term(
        factories=138,
        distance=21,
        distillation_tiles_per_factory=88,
        physical_qubits_per_d2=2.0,
        source="sensitivity_test",
        model="synthetic_double_factory_tiles",
    )

    assert data.value == 88200
    assert f88.value == 2 * f44.value


def test_whole_machine_partial_accounting_baseline():
    result = run("configs/baseline.yaml")

    assert result["code_distance"] == 21
    assert result["factories"] == 138
    assert result["throughput_binding_status"] == "unverified"

    # 88,200 data + 5,355,504 distillation + 1,582,308 storage.
    assert result["known_subtotal_physical_qubits"] == 7_026_012

    # Routing and workspace are deliberately missing, so no total is reported.
    assert result["total_physical_qubits"] is None
    assert result["accounting_complete"] is False
    assert set(result["missing_terms"]) == {"routing_qubits", "workspace_qubits"}

    assert result["known_subtotal_stv_qubit_seconds"] == pytest.approx(
        25_258_705_358.74778,
        rel=1e-12,
    )
