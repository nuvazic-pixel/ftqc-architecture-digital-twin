from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from experiments.multi_factory_pareto_search import run


def compare(
    *,
    unrouted_config: str,
    routed_config: str,
) -> dict[str, object]:
    unrouted = run(unrouted_config)
    routed = run(routed_config)

    unrouted_by_id = {
        str(row["candidate_id"]): row
        for row in unrouted["feasible_candidates"]
    }
    routed_by_id = {
        str(row["candidate_id"]): row
        for row in routed["feasible_candidates"]
    }

    shared_ids = sorted(set(unrouted_by_id) & set(routed_by_id))
    rows: list[dict[str, object]] = []

    for candidate_id in shared_ids:
        old = unrouted_by_id[candidate_id]
        new = routed_by_id[candidate_id]

        old_qubits = int(old["physical_qubits"])
        new_qubits = int(new["physical_qubits"])
        delta = new_qubits - old_qubits

        rows.append(
            {
                "candidate_id": candidate_id,
                "factory_count": new["factory_count"],
                "buffer_capacity_states": new["buffer_capacity_states"],
                "initial_buffer_states": new["initial_buffer_states"],
                "phase_policy": new["phase_policy"],
                "code_distance_unrouted": old["code_distance"],
                "code_distance_routed": new["code_distance"],
                "routing_tiles": new["routing_tiles"],
                "routing_physical_qubits": new[
                    "routing_physical_qubits"
                ],
                "physical_qubits_unrouted": old_qubits,
                "physical_qubits_routed": new_qubits,
                "physical_qubits_delta": delta,
                "physical_qubits_increase_fraction": (
                    0.0 if old_qubits == 0 else delta / old_qubits
                ),
                "probability_any_starvation_unrouted": old[
                    "probability_any_starvation"
                ],
                "probability_any_starvation_routed": new[
                    "probability_any_starvation"
                ],
                "pareto_unrouted": old["is_pareto"],
                "pareto_routed": new["is_pareto"],
                "pareto_status_changed": (
                    bool(old["is_pareto"]) != bool(new["is_pareto"])
                ),
            }
        )

    targets = sorted(
        set(unrouted["risk_target_views"])
        | set(routed["risk_target_views"])
    )
    reference_stability: dict[str, dict[str, object]] = {}

    for target in targets:
        old_ref = unrouted["risk_target_views"].get(target)
        new_ref = routed["risk_target_views"].get(target)

        old_id = None if old_ref is None else old_ref["candidate_id"]
        new_id = None if new_ref is None else new_ref["candidate_id"]

        reference_stability[target] = {
            "unrouted_candidate_id": old_id,
            "routed_candidate_id": new_id,
            "unchanged": old_id == new_id,
        }

    changed_frontier = [
        row["candidate_id"]
        for row in rows
        if row["pareto_status_changed"]
    ]

    return {
        "unrouted_scope": unrouted["scope"],
        "routed_scope": routed["scope"],
        "routing_model": routed["routing_model"],
        "routing_source": routed["routing_source"],
        "shared_candidate_count": len(rows),
        "reference_policy_stability": reference_stability,
        "all_reference_policies_unchanged": all(
            item["unchanged"]
            for item in reference_stability.values()
        ),
        "pareto_status_changed_count": len(changed_frontier),
        "pareto_status_changed_candidates": changed_frontier,
        "candidate_deltas": rows,
    }


def write_outputs(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_path = output_path / "routing_impact_comparison.json"
    csv_path = output_path / "routing_impact_comparison.csv"

    json_path.write_text(
        json.dumps(result, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    rows = list(result["candidate_deltas"])
    fieldnames = sorted(
        {key for row in rows for key in row.keys()}
    )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return {
        "json": str(json_path),
        "csv": str(csv_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--unrouted-config",
        default="configs/litinski_multi_factory_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--routed-config",
        default="configs/litinski_multi_factory_routed_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/routing_impact",
    )
    args = parser.parse_args()

    result = compare(
        unrouted_config=args.unrouted_config,
        routed_config=args.routed_config,
    )
    outputs = write_outputs(result, output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "summary": {
                    "shared_candidate_count": result[
                        "shared_candidate_count"
                    ],
                    "all_reference_policies_unchanged": result[
                        "all_reference_policies_unchanged"
                    ],
                    "pareto_status_changed_count": result[
                        "pareto_status_changed_count"
                    ],
                    "reference_policy_stability": result[
                        "reference_policy_stability"
                    ],
                },
                "outputs": outputs,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
