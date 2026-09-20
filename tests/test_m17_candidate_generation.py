from __future__ import annotations

from pathlib import Path

from experiments.m17_candidate_generation import (
    run,
    write_output,
)
from simulator.m17_candidate import (
    BeamSearchConfig,
    diversity_summary,
    generate_layout_candidate_specs,
    topology_class_for_sharing,
)


def _config() -> BeamSearchConfig:
    return BeamSearchConfig(
        beam_width=12,
        sharing_degrees=(0.0, 0.25, 0.5, 0.75, 1.0),
        variants_per_degree=3,
        min_placement_radius_tiles=8,
        max_placement_radius_tiles=28,
        clearance_tiles=1,
    )


def test_generator_spans_isolated_to_shared_trunk_endpoints():
    candidates = generate_layout_candidate_specs(
        factory_count=3,
        config=_config(),
    )
    summary = diversity_summary(candidates)

    assert len(candidates) == 15
    assert summary["contains_isolated_endpoint"] is True
    assert summary["contains_shared_trunk_endpoint"] is True
    assert summary["sharing_degrees"] == [
        0.0,
        0.25,
        0.5,
        0.75,
        1.0,
    ]


def test_sharing_degree_controls_compactness_monotonically():
    candidates = generate_layout_candidate_specs(
        factory_count=2,
        config=_config(),
    )

    radius_by_degree = {}
    for candidate in candidates:
        radius_by_degree.setdefault(
            candidate.corridor_sharing_degree,
            candidate.placement_radius_tiles,
        )

    assert radius_by_degree == {
        0.0: 28,
        0.25: 23,
        0.5: 18,
        0.75: 13,
        1.0: 8,
    }


def test_topology_classification_is_explicit():
    assert topology_class_for_sharing(0.0) == "isolated"
    assert topology_class_for_sharing(0.25) == "low_share"
    assert topology_class_for_sharing(0.5) == "balanced"
    assert topology_class_for_sharing(0.75) == "high_share"
    assert topology_class_for_sharing(1.0) == "shared_trunk"


def test_candidate_ids_are_deterministic_and_unique():
    first = generate_layout_candidate_specs(
        factory_count=4,
        config=_config(),
    )
    second = generate_layout_candidate_specs(
        factory_count=4,
        config=_config(),
    )

    assert [x.candidate_id for x in first] == [
        x.candidate_id for x in second
    ]
    assert len({x.candidate_id for x in first}) == len(first)


def test_experiment_generates_n2_n3_n4_candidate_grid():
    result = run("configs/m17_beam_floorplanner.yaml")

    assert result["candidate_count"] == 45
    assert result["diversity"]["factory_counts"] == [2, 3, 4]
    assert result["diversity"][
        "contains_isolated_endpoint"
    ] is True
    assert result["diversity"][
        "contains_shared_trunk_endpoint"
    ] is True


def test_candidate_output_is_machine_readable(tmp_path: Path):
    result = run("configs/m17_beam_floorplanner.yaml")
    path = write_output(
        result,
        output_path=tmp_path / "candidates.json",
    )

    output = Path(path)
    assert output.exists()
    assert output.stat().st_size > 1000
