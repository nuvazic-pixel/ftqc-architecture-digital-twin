from __future__ import annotations

import argparse
import json

from experiments.multi_factory_pareto_search import run


def compare_models(
    *,
    unrouted_config: str,
    manhattan_config: str,
    floorplan_config: str,
) -> dict[str, object]:
    unrouted = run(unrouted_config)
    manhattan = run(manhattan_config)
    floorplan = run(floorplan_config)

    targets = sorted(
        set(unrouted["risk_target_views"])
        | set(manhattan["risk_target_views"])
        | set(floorplan["risk_target_views"])
    )

    references: dict[str, dict[str, object]] = {}
    for target in targets:
        base = unrouted["risk_target_views"].get(target)
        linear = manhattan["risk_target_views"].get(target)
        packed = floorplan["risk_target_views"].get(target)

        base_id = None if base is None else base["candidate_id"]
        linear_id = None if linear is None else linear["candidate_id"]
        packed_id = None if packed is None else packed["candidate_id"]

        references[target] = {
            "unrouted": base_id,
            "manhattan": linear_id,
            "floorplan": packed_id,
            "floorplan_matches_unrouted": packed_id == base_id,
            "floorplan_matches_manhattan": packed_id == linear_id,
        }

    manhattan_rows = {
        str(row["candidate_id"]): row
        for row in manhattan["feasible_candidates"]
    }
    floorplan_rows = {
        str(row["candidate_id"]): row
        for row in floorplan["feasible_candidates"]
    }

    key_candidates = (
        "N2_B048_STAG_I012",
        "N2_B048_SYNC_I024",
        "N3_B048_SYNC_I024",
        "N3_B048_STAG_I024",
        "N2_B096_STAG_I048",
        "N3_B096_STAG_I048",
        "N4_B096_STAG_I048",
    )

    footprint_comparison: list[dict[str, object]] = []
    for candidate_id in key_candidates:
        old = manhattan_rows[candidate_id]
        new = floorplan_rows[candidate_id]
        footprint_comparison.append(
            {
                "candidate_id": candidate_id,
                "manhattan_routing_tiles": old["routing_tiles"],
                "floorplan_routing_tiles": new["routing_tiles"],
                "floorplan_total_route_union_tiles": new[
                    "floorplan_total_route_union_tiles"
                ],
                "physical_qubits_manhattan": old["physical_qubits"],
                "physical_qubits_floorplan": new["physical_qubits"],
                "physical_qubits_delta_floorplan_minus_manhattan": (
                    int(new["physical_qubits"])
                    - int(old["physical_qubits"])
                ),
            }
        )

    return {
        "unrouted_model": unrouted["routing_model"],
        "manhattan_model": manhattan["routing_model"],
        "floorplan_model": floorplan["routing_model"],
        "reference_policy_comparison": references,
        "all_floorplan_references_match_unrouted": all(
            item["floorplan_matches_unrouted"]
            for item in references.values()
        ),
        "all_floorplan_references_match_manhattan": all(
            item["floorplan_matches_manhattan"]
            for item in references.values()
        ),
        "footprint_comparison": footprint_comparison,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--unrouted-config",
        default="configs/litinski_multi_factory_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--manhattan-config",
        default=(
            "configs/litinski_multi_factory_routed_pareto_10mT.yaml"
        ),
    )
    parser.add_argument(
        "--floorplan-config",
        default=(
            "configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml"
        ),
    )
    args = parser.parse_args()

    result = compare_models(
        unrouted_config=args.unrouted_config,
        manhattan_config=args.manhattan_config,
        floorplan_config=args.floorplan_config,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
