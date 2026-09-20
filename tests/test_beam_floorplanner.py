from __future__ import annotations

from pathlib import Path

import pytest

from experiments.m17_beam_layout_search import (
    run,
    write_outputs,
)
from simulator.beam_floorplanner import (
    generate_layout_candidates,
)


@pytest.fixture(scope="module")
def search_result() -> dict[str, object]:
    return run(
        "configs/litinski_m17_beam_layout_search.yaml"
    )


def test_layout_candidate_has_explicit_spatial_metrics():
    candidate = generate_layout_candidates(
        factory_count=2,
        data_block_tiles=153,
        shared_buffer_tiles=52,
        factory_tiles=44,
        sharing_target=0.5,
        beam_width=6,
        final_candidates=1,
        clearance_tiles=1,
        search_margin_tiles=24,
    )[0]

    assert candidate.factory_count == 2
    assert 0.0 <= candidate.sharing_fraction <= 1.0
    assert candidate.factory_route_union_tiles > 0
    assert candidate.factory_route_incidence_tiles >= (
        candidate.factory_route_union_tiles
    )
    assert candidate.bbox_area_tiles > 0
    assert len(candidate.floorplan.placements) == 4


def test_sharing_target_changes_candidate_geometry():
    disjoint = generate_layout_candidates(
        factory_count=4,
        data_block_tiles=153,
        shared_buffer_tiles=104,
        factory_tiles=44,
        sharing_target=0.0,
        beam_width=10,
        final_candidates=1,
    )[0]

    shared = generate_layout_candidates(
        factory_count=4,
        data_block_tiles=153,
        shared_buffer_tiles=104,
        factory_tiles=44,
        sharing_target=1.0,
        beam_width=10,
        final_candidates=1,
    )[0]

    assert (
        shared.sharing_fraction
        >= disjoint.sharing_fraction
    )
    assert (
        shared.shared_factory_route_cells
        >= disjoint.shared_factory_route_cells
    )


def test_m17_search_generates_expected_grid(
    search_result: dict[str, object],
):
    assert search_result["candidate_count"] == 27
    assert search_result["pareto_candidate_count"] > 0

    scenarios = {
        row["scenario"]
        for row in search_result["candidates"]
    }
    assert scenarios == {
        "N2_B048",
        "N3_B048",
        "N4_B096",
    }

    targets = {
        row["sharing_target"]
        for row in search_result["candidates"]
    }
    assert targets == {0.0, 0.5, 1.0}


def test_all_m17_candidates_are_lossless_in_m16_stress(
    search_result: dict[str, object],
):
    assert all(
        row["all_generated_states_delivered"]
        for row in search_result["candidates"]
    )


def test_outputs_are_machine_readable(
    tmp_path: Path,
    search_result: dict[str, object],
):
    paths = write_outputs(
        search_result,
        output_dir=tmp_path,
    )

    assert set(paths) == {
        "json",
        "candidates_csv",
        "pareto_csv",
    }
    for path in paths.values():
        output = Path(path)
        assert output.exists()
        assert output.stat().st_size > 0


def test_m17_corridor_sharing_tradeoff_is_locked(
    search_result: dict[str, object],
):
    rows = {
        (row["scenario"], row["candidate_id"]): row
        for row in search_result["candidates"]
    }

    n2_disjoint = rows[("N2_B048", "N2_S0.00_R01")]
    n2_shared = rows[("N2_B048", "N2_S1.00_R01")]

    assert n2_disjoint["sharing_fraction"] == 0.0
    assert n2_disjoint["factory_route_union_tiles"] == 2
    assert n2_disjoint["blocked_after_service_ticks"] == 0
    assert n2_disjoint["suppressed_factory_events"] == 0

    assert n2_shared["sharing_fraction"] == pytest.approx(
        0.23529411764705888
    )
    assert n2_shared["shared_factory_route_cells"] == 4
    assert n2_shared["factory_route_union_tiles"] == 13
    assert n2_shared["route_savings_vs_disjoint_incidence"] == 4
    assert n2_shared["blocked_after_service_ticks"] == 11622
    assert n2_shared["suppressed_factory_events"] == 0

    n3_shared = rows[("N3_B048", "N3_S1.00_R01")]
    assert n3_shared["sharing_fraction"] == pytest.approx(
        0.45945945945945943
    )
    assert n3_shared["shared_factory_route_cells"] == 13
    assert n3_shared["max_factory_route_multiplicity"] == 3
    assert n3_shared["blocked_after_service_ticks"] == 223782
    assert n3_shared["suppressed_factory_events"] == 88

    n4_shared = rows[("N4_B096", "N4_S1.00_R01")]
    assert n4_shared["sharing_fraction"] == pytest.approx(
        0.5802469135802469
    )
    assert n4_shared["shared_factory_route_cells"] == 28
    assert n4_shared["max_factory_route_multiplicity"] == 4
    assert n4_shared["blocked_after_service_ticks"] == 407824
    assert n4_shared["suppressed_factory_events"] == 132


def test_m17_pareto_is_scoped_per_architecture_scenario(
    search_result: dict[str, object],
):
    assert search_result["pareto_scope"] == "within_scenario_only"
    assert set(search_result["pareto_counts_by_scenario"]) == {
        "N2_B048",
        "N3_B048",
        "N4_B096",
    }
    assert all(
        count > 0
        for count in search_result["pareto_counts_by_scenario"].values()
    )

    # The intentionally over-shared R01 candidates are dominated inside each
    # comparable scenario by shorter, non-congested layouts.
    by_id = {
        (row["scenario"], row["candidate_id"]): row
        for row in search_result["candidates"]
    }
    assert by_id[("N2_B048", "N2_S1.00_R01")]["is_pareto"] is False
    assert by_id[("N3_B048", "N3_S1.00_R01")]["is_pareto"] is False
    assert by_id[("N4_B096", "N4_S1.00_R01")]["is_pareto"] is False
