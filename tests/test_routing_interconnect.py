from __future__ import annotations

from pathlib import Path

import pytest

from experiments.multi_factory_pareto_search import run
from experiments.routing_pareto_comparison import compare, write_outputs
from simulator.routing_interconnect import (
    manhattan_trunk_and_spur_footprint,
    square_envelope_factory_span,
)


@pytest.fixture(scope="module")
def unrouted_result() -> dict[str, object]:
    return run("configs/litinski_multi_factory_pareto_10mT.yaml")


@pytest.fixture(scope="module")
def routed_result() -> dict[str, object]:
    return run("configs/litinski_multi_factory_routed_pareto_10mT.yaml")


@pytest.fixture(scope="module")
def comparison_result() -> dict[str, object]:
    return compare(
        unrouted_config="configs/litinski_multi_factory_pareto_10mT.yaml",
        routed_config=(
            "configs/litinski_multi_factory_routed_pareto_10mT.yaml"
        ),
    )


def test_44_tile_factory_compact_envelope_span_is_explicit():
    assert square_envelope_factory_span(factory_tile_area=44) == 7


def test_manhattan_routing_tiles_scale_from_embedded_one_factory_baseline():
    expected = {
        1: 0,
        2: 9,
        3: 18,
        4: 27,
    }

    for factories, routing_tiles in expected.items():
        footprint = manhattan_trunk_and_spur_footprint(
            factory_count=factories,
            factory_tile_area=44,
            baseline_factory_count=1,
            clearance_tiles=1,
            lane_width_tiles=1,
            branch_spur_tiles=1,
        )
        assert footprint.effective_factory_span_tiles == 7
        assert footprint.slot_pitch_tiles == 8
        assert footprint.total_routing_tiles == routing_tiles


def test_unrouted_milestone_11_remains_reproducible(
    unrouted_result: dict[str, object],
):
    assert unrouted_result["routing_interconnect_status"] == "unmodeled"
    assert unrouted_result["routing_model"] == "unmodeled"

    candidates = {
        row["candidate_id"]: row
        for row in unrouted_result["feasible_candidates"]
    }
    assert candidates["N2_B048_SYNC_I012"]["physical_qubits"] == 427_194


def test_routed_candidate_accounts_for_interconnect_tiles(
    routed_result: dict[str, object],
):
    assert (
        routed_result["routing_interconnect_status"]
        == "modeled_spatial_lower_bound"
    )
    assert routed_result["routing_model"] == "manhattan_trunk_and_spur_v1"

    candidates = {
        row["candidate_id"]: row
        for row in routed_result["feasible_candidates"]
    }

    two_factory = candidates["N2_B048_SYNC_I012"]
    assert two_factory["routing_tiles"] == 9
    assert two_factory["routing_physical_qubits"] == 13_122
    assert two_factory["physical_qubits"] == 440_316

    three_factory = candidates["N3_B048_SYNC_I024"]
    assert three_factory["routing_tiles"] == 18
    assert three_factory["routing_physical_qubits"] == 26_244
    assert three_factory["physical_qubits"] == 517_590

    four_factory = candidates["N4_B096_STAG_I048"]
    assert four_factory["routing_tiles"] == 27
    assert four_factory["routing_physical_qubits"] == 39_366
    assert four_factory["physical_qubits"] == 670_680


def test_routing_footprint_does_not_silently_change_transport_risk(
    unrouted_result: dict[str, object],
    routed_result: dict[str, object],
):
    old = {
        row["candidate_id"]: row
        for row in unrouted_result["feasible_candidates"]
    }
    new = {
        row["candidate_id"]: row
        for row in routed_result["feasible_candidates"]
    }

    candidate_id = "N2_B048_STAG_I012"
    assert new[candidate_id]["probability_any_starvation"] == pytest.approx(
        old[candidate_id]["probability_any_starvation"],
        rel=0.0,
        abs=0.0,
    )
    assert new[candidate_id]["physical_qubits"] > old[candidate_id][
        "physical_qubits"
    ]


def test_routing_comparison_rechecks_reference_policy_stability(
    comparison_result: dict[str, object],
):
    assert comparison_result["shared_candidate_count"] == 42
    assert comparison_result["routing_model"] == "manhattan_trunk_and_spur_v1"

    references = comparison_result["reference_policy_stability"]
    assert references["0.01"]["routed_candidate_id"] == (
        "N2_B048_STAG_I012"
    )
    assert references["0.0001"]["routed_candidate_id"] == (
        "N2_B048_SYNC_I024"
    )
    assert references["1e-06"]["routed_candidate_id"] == (
        "N3_B048_SYNC_I024"
    )


def test_routing_comparison_writes_machine_readable_outputs(
    tmp_path: Path,
    comparison_result: dict[str, object],
):
    paths = write_outputs(comparison_result, output_dir=tmp_path)

    assert set(paths) == {"json", "csv"}
    for path in paths.values():
        file_path = Path(path)
        assert file_path.exists()
        assert file_path.stat().st_size > 0
