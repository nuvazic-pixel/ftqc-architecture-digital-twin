from __future__ import annotations

import json
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


def test_discover_m17_corridor_sharing_profile(
    search_result: dict[str, object],
):
    profile = [
        {
            key: row[key]
            for key in (
                "scenario",
                "candidate_id",
                "sharing_target",
                "sharing_fraction",
                "factory_route_union_tiles",
                "route_savings_vs_disjoint_incidence",
                "shared_factory_route_cells",
                "max_factory_route_multiplicity",
                "max_factory_path_tiles",
                "bbox_area_tiles",
                "blocked_after_service_ticks",
                "suppressed_factory_events",
                "max_network_states",
                "fraction_event_boundaries_with_carryover",
                "mean_batch_latency_logical_steps",
                "max_batch_latency_logical_steps",
                "is_pareto",
            )
        }
        for row in search_result["candidates"]
    ]

    raise AssertionError(
        json.dumps(profile, indent=2, sort_keys=True)
    )
