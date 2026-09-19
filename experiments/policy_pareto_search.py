from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

from experiments.prefill_policy_sensitivity import run as run_prefill
from metrics.pareto import Objective, pareto_partition
from simulator.config import load_config


def _candidate_id(capacity: int, fill_fraction: float) -> str:
    return f"B{capacity:03d}_F{int(round(fill_fraction * 100)):03d}"


def _risk_target_reference(
    candidates: Iterable[dict[str, object]],
    *,
    max_starvation_probability: float,
) -> dict[str, object] | None:
    eligible = [
        candidate
        for candidate in candidates
        if float(candidate["probability_any_starvation"])
        <= max_starvation_probability
    ]
    if not eligible:
        return None

    return min(
        eligible,
        key=lambda row: (
            int(row["physical_qubits"]),
            float(row["expected_prefill_seconds"]),
            float(row["probability_any_starvation"]),
        ),
    )


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    search_cfg = config["policy_search"]

    prefill_result = run_prefill(config_path)
    max_campaign_failure = float(
        search_cfg["feasibility"][
            "max_conservative_expected_campaign_failure_budget"
        ]
    )

    candidates: list[dict[str, object]] = []
    infeasible: list[dict[str, object]] = []

    for raw in prefill_result["results"]:
        row = dict(raw)
        capacity = int(row["buffer_capacity_states"])
        fill_fraction = float(row["fill_fraction"])
        row["candidate_id"] = _candidate_id(capacity, fill_fraction)
        row["expected_prefill_milliseconds"] = (
            float(row["expected_prefill_seconds"]) * 1000.0
        )
        row["survival_difficulty"] = -float(
            row["log10_probability_no_starvation"]
        )

        if (
            float(row["conservative_expected_campaign_failure_budget"])
            <= max_campaign_failure
        ):
            candidates.append(row)
        else:
            row["feasibility_reason"] = "campaign_failure_budget"
            infeasible.append(row)

    objectives = [
        Objective(
            metric=str(item["metric"]),
            direction=str(item["direction"]),
        )
        for item in search_cfg["objectives"]
    ]

    frontier, dominated = pareto_partition(candidates, objectives)
    frontier_ids = {str(row["candidate_id"]) for row in frontier}

    all_feasible: list[dict[str, object]] = []
    dominated_by_id = {
        str(row["candidate_id"]): row["dominated_by"]
        for row in dominated
    }
    for row in candidates:
        enriched = dict(row)
        candidate_id = str(row["candidate_id"])
        enriched["is_pareto"] = candidate_id in frontier_ids
        enriched["dominated_by"] = dominated_by_id.get(candidate_id, [])
        all_feasible.append(enriched)

    frontier = sorted(
        frontier,
        key=lambda row: (
            int(row["physical_qubits"]),
            float(row["expected_prefill_seconds"]),
            -float(row["log10_probability_no_starvation"]),
        ),
    )
    all_feasible = sorted(
        all_feasible,
        key=lambda row: (
            int(row["physical_qubits"]),
            float(row["expected_prefill_seconds"]),
            float(row["fill_fraction"]),
        ),
    )

    risk_target_views: dict[str, dict[str, object] | None] = {}
    for target in search_cfg["risk_target_views"]:
        target = float(target)
        reference = _risk_target_reference(
            frontier,
            max_starvation_probability=target,
        )
        risk_target_views[f"{target:.10g}"] = (
            None if reference is None else {
                "candidate_id": reference["candidate_id"],
                "buffer_capacity_states": reference["buffer_capacity_states"],
                "fill_fraction": reference["fill_fraction"],
                "physical_qubits": reference["physical_qubits"],
                "expected_prefill_seconds": reference[
                    "expected_prefill_seconds"
                ],
                "probability_any_starvation": reference[
                    "probability_any_starvation"
                ],
            }
        )

    return {
        "scope": config["resource_model"]["scope"],
        "method": search_cfg["method"],
        "candidate_count": len(prefill_result["results"]),
        "feasible_candidate_count": len(all_feasible),
        "infeasible_candidate_count": len(infeasible),
        "pareto_candidate_count": len(frontier),
        "objectives": [
            {
                "metric": objective.metric,
                "direction": objective.direction,
            }
            for objective in objectives
        ],
        "feasible_candidates": all_feasible,
        "pareto_frontier": frontier,
        "infeasible_candidates": infeasible,
        "risk_target_views": risk_target_views,
        "reference_selection_rule": search_cfg["reference_selection"]["rule"],
    }


def write_outputs(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_path = output_path / "policy_pareto.json"
    candidates_path = output_path / "policy_candidates.csv"
    frontier_path = output_path / "policy_pareto.csv"

    json_path.write_text(
        json.dumps(result, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    candidates = list(result["feasible_candidates"])
    frontier = list(result["pareto_frontier"])

    fieldnames = sorted(
        {
            key
            for row in (*candidates, *frontier)
            for key in row.keys()
            if key != "dominated_by"
        }
    )

    for path, rows in (
        (candidates_path, candidates),
        (frontier_path, frontier),
    ):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                serializable = {
                    key: row.get(key)
                    for key in fieldnames
                }
                writer.writerow(serializable)

    return {
        "json": str(json_path),
        "candidates_csv": str(candidates_path),
        "pareto_csv": str(frontier_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_policy_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/policy_pareto",
    )
    args = parser.parse_args()

    result = run(args.config)
    paths = write_outputs(result, output_dir=args.output_dir)
    print(
        json.dumps(
            {
                "summary": {
                    "candidate_count": result["candidate_count"],
                    "feasible_candidate_count": result[
                        "feasible_candidate_count"
                    ],
                    "pareto_candidate_count": result[
                        "pareto_candidate_count"
                    ],
                    "risk_target_views": result["risk_target_views"],
                },
                "outputs": paths,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
