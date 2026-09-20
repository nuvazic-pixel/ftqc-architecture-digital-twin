from __future__ import annotations

from pathlib import Path

import pytest

from experiments.m17b_beam_search import (
    run,
    write_outputs,
)
from experiments.plot_m17b_pareto import plot_pareto
from simulator.m17_candidate import (
    BeamSearchConfig,
    generate_layout_candidate_specs,
)
from simulator.m17_materializer import (
    materialize_diverse_beam,
)


@pytest.fixture(scope="module")
def result() -> dict[str, object]:
    return run("configs/m17b_beam_materializer.yaml")


def _specs(factory_count: int):
    config = BeamSearchConfig(
        beam_width=12,
        sharing_degrees=(0.0, 0.25, 0.5, 0.75, 1.0),
        variants_per_degree=3,
        min_placement_radius_tiles=8,
        max_placement_radius_tiles=28,
        clearance_tiles=1,
    )
    return generate_layout_candidate_specs(
        factory_count=factory_count,
        config=config,
    )


def test_diversity_injection_survives_every_factory_step():
    layouts = materialize_diverse_beam(
        specs=_specs(3),
        data_block_tiles=153,
        shared_buffer_tiles=52,
        factory_tiles=44,
        beam_width=12,
        search_margin_tiles=36,
    )

    assert len(layouts) == 12
    assert {
        layout.spec.corridor_sharing_degree
        for layout in layouts
    } == {0.0, 0.25, 0.5, 0.75, 1.0}


def test_materialized_layouts_have_explicit_paths_and_no_block_overlap():
    layouts = materialize_diverse_beam(
        specs=_specs(2),
        data_block_tiles=153,
        shared_buffer_tiles=52,
        factory_tiles=44,
        beam_width=12,
        search_margin_tiles=36,
    )

    for layout in layouts:
        assert set(layout.factory_paths) == {1, 2}
        assert all(
            len(path) > 0
            for path in layout.factory_paths.values()
        )

        seen = set()
        for placement in layout.floorplan.placements:
            cells = set(placement.cells)
            assert not (seen & cells)
            seen.update(cells)


def test_m17b_evaluates_exactly_one_diverse_beam_per_factory_count(
    result: dict[str, object],
):
    assert result["candidate_count"] == 36

    for factory_count in ("2", "3", "4"):
        assert len(result["beam_survivors"][factory_count]) == 12

    for factory_count in (2, 3, 4):
        degrees = {
            float(row["corridor_sharing_degree"])
            for row in result["candidates"]
            if int(row["factory_count"]) == factory_count
        }
        assert degrees == {0.0, 0.25, 0.5, 0.75, 1.0}


def test_m17b_is_lossless_for_generated_states(
    result: dict[str, object],
):
    assert all(
        row["all_generated_states_delivered"] is True
        for row in result["candidates"]
    )


def test_starvation_probability_is_explicitly_deferred_to_m18(
    result: dict[str, object],
):
    assert result["starvation_probability_status"] == (
        "deferred_to_M18"
    )
    assert all(
        row["starvation_probability"] is None
        for row in result["candidates"]
    )


def test_outputs_and_pareto_plot_are_machine_readable(
    tmp_path: Path,
    result: dict[str, object],
):
    paths = write_outputs(
        result,
        output_dir=tmp_path,
    )
    plot_path = plot_pareto(
        result,
        output_path=tmp_path / "pareto.png",
    )

    for path in (*paths.values(), plot_path):
        output = Path(path)
        assert output.exists()
        assert output.stat().st_size > 1000


def test_corridor_sharing_tipping_profile_is_locked(
    result: dict[str, object],
):
    assert result["pareto_candidate_count"] == 7
    assert result["first_backpressure_sharing_degree"] == 1.0
    assert result["first_backpressure_bracket"] == {
        "last_sample_without_backpressure": 0.75,
        "first_sample_with_backpressure": 1.0,
    }

    sweep = {
        float(row["corridor_sharing_degree"]): row
        for row in result["corridor_sharing_sweep"]
    }

    for degree in (0.0, 0.25, 0.5, 0.75):
        assert sweep[degree]["backpressure_candidate_count"] == 0
        assert sweep[degree]["max_shared_factory_route_cells"] == 0

    assert sweep[1.0]["backpressure_candidate_count"] == 3
    assert sweep[1.0]["max_shared_factory_route_cells"] == 16
    assert sweep[1.0]["max_actual_route_overlap_fraction"] == pytest.approx(
        4 / 9
    )
    assert sweep[1.0]["max_suppressed_factory_events"] == 0

    frontier = {
        (
            int(row["factory_count"]),
            float(row["corridor_sharing_degree"]),
        ): row
        for row in result["pareto_frontier"]
    }

    n2_shared = frontier[(2, 1.0)]
    assert n2_shared["physical_qubits"] == 454_896
    assert n2_shared["shared_factory_route_cells"] == 8
    assert n2_shared["blocked_time_seconds"] == pytest.approx(
        0.081243
    )

    n3_shared = frontier[(3, 1.0)]
    assert n3_shared["physical_qubits"] == 530_712
    assert n3_shared["shared_factory_route_cells"] == 8
    assert n3_shared["blocked_time_seconds"] == pytest.approx(
        0.013689
    )

    n4_shared = frontier[(4, 1.0)]
    assert n4_shared["physical_qubits"] == 689_634
    assert n4_shared["shared_factory_route_cells"] == 16
    assert n4_shared["blocked_time_seconds"] == pytest.approx(
        0.016443
    )
