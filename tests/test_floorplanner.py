from __future__ import annotations

from pathlib import Path

import pytest

from experiments.floorplan_model_comparison import compare_models
from experiments.multi_factory_pareto_search import run
from experiments.render_floorplan import render_floorplan
from simulator.floorplanner import (
    build_greedy_floorplan,
    compact_raster_shape,
)


@pytest.fixture(scope="module")
def floorplan_result() -> dict[str, object]:
    return run(
        "configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml"
    )


@pytest.fixture(scope="module")
def model_comparison() -> dict[str, object]:
    return compare_models(
        unrouted_config="configs/litinski_multi_factory_pareto_10mT.yaml",
        manhattan_config=(
            "configs/litinski_multi_factory_routed_pareto_10mT.yaml"
        ),
        floorplan_config=(
            "configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml"
        ),
    )


def test_compact_raster_preserves_exact_tile_area():
    factory = compact_raster_shape(name="factory", tile_area=44)
    data = compact_raster_shape(name="data", tile_area=153)

    assert (factory.width, factory.height) == (7, 7)
    assert len(factory.cells) == 44
    assert (data.width, data.height) == (13, 12)
    assert len(data.cells) == 153


def test_greedy_floorplanner_builds_real_2d_multi_factory_layout():
    layout = build_greedy_floorplan(
        factory_count=2,
        data_block_tiles=153,
        shared_buffer_tiles=52,
        factory_tiles=44,
        clearance_tiles=1,
        search_margin_tiles=24,
    )

    placements = {
        placement.name: placement
        for placement in layout.placements
    }

    assert (placements["data_block"].x, placements["data_block"].y) == (0, 0)
    assert (placements["shared_buffer"].x, placements["shared_buffer"].y) == (
        14,
        2,
    )
    assert (placements["factory_1"].x, placements["factory_1"].y) == (23, 2)
    assert (placements["factory_2"].x, placements["factory_2"].y) == (14, 10)

    assert layout.route_union_tiles == 3
    assert layout.bbox == (0, 0, 29, 16)
    assert layout.bbox_area_tiles == 510


def test_floorplan_incremental_routing_is_not_linear_manhattan_proxy(
    floorplan_result: dict[str, object],
):
    candidates = {
        row["candidate_id"]: row
        for row in floorplan_result["feasible_candidates"]
    }

    two = candidates["N2_B048_STAG_I012"]
    three = candidates["N3_B048_SYNC_I024"]
    four = candidates["N4_B096_STAG_I048"]

    assert two["floorplan_total_route_union_tiles"] == 3
    assert two["floorplan_embedded_baseline_route_tiles"] == 2
    assert two["routing_tiles"] == 1
    assert two["physical_qubits"] == 428_652

    assert three["routing_tiles"] == 2
    assert three["physical_qubits"] == 494_262

    assert four["routing_tiles"] == 11
    assert four["physical_qubits"] == 647_352


def test_floorplanned_pareto_reverts_moderate_risk_references(
    floorplan_result: dict[str, object],
):
    views = floorplan_result["risk_target_views"]

    expected = {
        "0.01": "N2_B048_STAG_I012",
        "0.0001": "N2_B048_SYNC_I024",
        "1e-06": "N3_B048_SYNC_I024",
        "1e-09": "N3_B048_STAG_I024",
        "1e-12": "N2_B096_STAG_I048",
        "1e-18": "N3_B096_STAG_I048",
        "1e-24": "N4_B096_STAG_I048",
    }

    assert {
        target: item["candidate_id"]
        for target, item in views.items()
    } == expected


def test_three_model_comparison_shows_routing_model_sensitivity(
    model_comparison: dict[str, object],
):
    assert model_comparison["manhattan_model"] == (
        "manhattan_trunk_and_spur_v1"
    )
    assert model_comparison["floorplan_model"] == (
        "greedy_compact_raster_astar_v1"
    )
    assert (
        model_comparison["all_floorplan_references_match_unrouted"]
        is True
    )
    assert (
        model_comparison["all_floorplan_references_match_manhattan"]
        is False
    )

    refs = model_comparison["reference_policy_comparison"]
    assert refs["0.01"] == {
        "unrouted": "N2_B048_STAG_I012",
        "manhattan": "N1_B096_SYNC_I024",
        "floorplan": "N2_B048_STAG_I012",
        "floorplan_matches_unrouted": True,
        "floorplan_matches_manhattan": False,
    }


def test_floorplan_renderer_writes_png(tmp_path: Path):
    path = render_floorplan(
        config_path=(
            "configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml"
        ),
        candidate_id="N2_B048_STAG_I012",
        output_path=tmp_path / "layout.png",
    )

    output = Path(path)
    assert output.exists()
    assert output.suffix == ".png"
    assert output.stat().st_size > 1000
