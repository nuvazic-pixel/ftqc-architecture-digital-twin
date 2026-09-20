from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulator.config import load_config
from simulator.m17_candidate import (
    BeamSearchConfig,
    diversity_summary,
    generate_layout_candidate_specs,
)


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    m17 = config["m17_floorplanner"]

    beam = BeamSearchConfig(
        beam_width=int(m17["beam_width"]),
        sharing_degrees=tuple(
            float(x) for x in m17["corridor_sharing_degrees"]
        ),
        variants_per_degree=int(
            m17["variants_per_degree"]
        ),
        min_placement_radius_tiles=int(
            m17["min_placement_radius_tiles"]
        ),
        max_placement_radius_tiles=int(
            m17["max_placement_radius_tiles"]
        ),
        clearance_tiles=int(m17["clearance_tiles"]),
    )

    all_candidates = []
    by_factory_count: dict[str, object] = {}

    for factory_count in m17["factory_counts"]:
        factory_count = int(factory_count)
        candidates = generate_layout_candidate_specs(
            factory_count=factory_count,
            config=beam,
        )
        all_candidates.extend(candidates)
        by_factory_count[str(factory_count)] = {
            "diversity": diversity_summary(candidates),
            "candidate_ids": [
                candidate.candidate_id
                for candidate in candidates
            ],
        }

    return {
        "milestone": "M17",
        "phase": "candidate_schema_and_topology_generator",
        "engine_status": "foundation",
        "beam_width": beam.beam_width,
        "candidate_count": len(all_candidates),
        "diversity": diversity_summary(all_candidates),
        "by_factory_count": by_factory_count,
        "candidates": [
            candidate.to_dict()
            for candidate in all_candidates
        ],
        "next_evaluator": (
            "materialize placements/routes and evaluate each candidate "
            "through the M16 finite-buffer backpressure simulator"
        ),
    }


def write_output(
    result: dict[str, object],
    *,
    output_path: str | Path,
) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/m17_beam_floorplanner.yaml",
    )
    parser.add_argument(
        "--output",
        default="results/m17/candidate_specs.json",
    )
    args = parser.parse_args()

    result = run(args.config)
    output = write_output(
        result,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "diversity": result["diversity"],
                "output": output,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
