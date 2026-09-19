from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from metrics.pareto import Objective, pareto_partition
from metrics.space_time_volume import space_time_volume
from simulator.buffer_consumer import replicated_storage_tiles
from simulator.config import load_config
from simulator.multi_factory import (
    build_multi_factory_risk_kernel,
    multi_factory_startup_cost,
)
from simulator.system_reliability import logical_failure_budget_from_runtime


def _candidate_id(
    *,
    factories: int,
    capacity: int,
    phase_policy: str,
    initial_states: int,
) -> str:
    phase = "SYNC" if phase_policy == "synchronized" else "STAG"
    return (
        f"N{factories}_B{capacity:03d}_{phase}_I{initial_states:03d}"
    )


def _reference_for_risk_target(
    candidates: list[dict[str, object]],
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
            float(row["conservative_startup_seconds"]),
            float(row["probability_any_starvation"]),
        ),
    )


def _select_distance(
    *,
    config: dict[str, object],
    total_tiles: int,
    factories: int,
    phase_policy: str,
    initial_buffer_states: int,
) -> tuple[int, dict[str, float | int | str], float]:
    qec = config["qec"]
    protocol = config["factories"]["protocol"]
    search_cfg = config["multi_factory_search"]

    code_cycle_seconds = (
        config["hardware"]["timing_ns"]["code_cycle"]["value"] * 1e-9
    )
    nominal_runtime = float(
        search_cfg["consumer"]["nominal_runtime_seconds"]
    )
    max_failure = float(
        search_cfg["feasibility"][
            "max_conservative_campaign_failure_budget"
        ]
    )

    for distance in qec["allowed_distances"]:
        distance = int(distance)
        batch_duration = (
            distance
            * int(protocol["protocol_steps_per_batch"])
            * code_cycle_seconds
        )
        startup = multi_factory_startup_cost(
            initial_buffer_states=initial_buffer_states,
            factories=factories,
            phase_policy=phase_policy,
            batch_duration_seconds=batch_duration,
            output_states_per_successful_batch=int(
                protocol["output_states_per_batch"]
            ),
            batch_success_probability=float(
                protocol["batch_success_probability"]
            ),
        )
        campaign_runtime = (
            nominal_runtime + startup.conservative_startup_seconds
        )
        failure = logical_failure_budget_from_runtime(
            tile_count=total_tiles,
            runtime_seconds=campaign_runtime,
            code_cycle_time_seconds=code_cycle_seconds,
            distance=distance,
            physical_error=config["hardware"]["errors"]["p_2q"]["value"],
            physical_error_threshold=qec["physical_error_threshold"]["value"],
            fit_A=qec["fit_A"]["value"],
        )

        if failure <= max_failure:
            return (
                distance,
                {
                    "expected_prefill_seconds": startup.expected_prefill_seconds,
                    "phase_setup_seconds": startup.phase_setup_seconds,
                    "conservative_startup_seconds": (
                        startup.conservative_startup_seconds
                    ),
                    "successful_prefill_batches_required": (
                        startup.successful_batches_required
                    ),
                    "startup_accounting_model": startup.accounting_model,
                },
                failure,
            )

    raise ValueError(
        "No allowed code distance satisfies the conservative campaign "
        "failure budget for this multi-factory candidate."
    )


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)

    protocol = config["factories"]["protocol"]
    resource = config["resource_model"]
    search_cfg = config["multi_factory_search"]

    target_states = int(config["workload"]["t_count"])
    nominal_runtime_seconds = float(
        search_cfg["consumer"]["nominal_runtime_seconds"]
    )
    nominal_runtime_ns = int(round(nominal_runtime_seconds * 1e9))

    code_cycle_ns = int(
        config["hardware"]["timing_ns"]["code_cycle"]["value"]
    )
    tile_factor = float(
        resource["tile_model"]["physical_qubits_per_d2"]["value"]
    )
    data_tiles = int(resource["data_block"]["tiles"]["value"])
    shared_buffer_cfg = resource["shared_buffer"]

    candidates: list[dict[str, object]] = []
    infeasible: list[dict[str, object]] = []

    for factories in search_cfg["sensitivity"]["factory_counts"]:
        factories = int(factories)
        phase_policies = list(
            search_cfg["sensitivity"]["phase_policies"]
        )
        if factories == 1:
            phase_policies = ["synchronized"]

        for capacity in search_cfg["sensitivity"][
            "buffer_capacities_states"
        ]:
            capacity = int(capacity)

            storage_tiles = replicated_storage_tiles(
                buffer_capacity_states=capacity,
                base_capacity_states=int(
                    shared_buffer_cfg["base_capacity_states"]
                ),
                base_storage_tiles=int(
                    shared_buffer_cfg["base_storage_tiles"]
                ),
            )
            total_tiles = (
                data_tiles
                + factories * int(protocol["distillation_tiles"])
                + storage_tiles
            )

            for initial_states in search_cfg["sensitivity"][
                "initial_buffer_states"
            ]:
                initial_states = int(initial_states)
                if initial_states > capacity:
                    continue

                for phase_policy in phase_policies:
                    candidate_id = _candidate_id(
                        factories=factories,
                        capacity=capacity,
                        phase_policy=phase_policy,
                        initial_states=initial_states,
                    )

                    try:
                        distance, startup, campaign_failure = _select_distance(
                            config=config,
                            total_tiles=total_tiles,
                            factories=factories,
                            phase_policy=str(phase_policy),
                            initial_buffer_states=initial_states,
                        )
                    except ValueError as exc:
                        infeasible.append(
                            {
                                "candidate_id": candidate_id,
                                "factory_count": factories,
                                "buffer_capacity_states": capacity,
                                "initial_buffer_states": initial_states,
                                "phase_policy": phase_policy,
                                "reason": str(exc),
                            }
                        )
                        continue

                    batch_duration_ns = (
                        distance
                        * int(protocol["protocol_steps_per_batch"])
                        * code_cycle_ns
                    )
                    kernel = build_multi_factory_risk_kernel(
                        target_states=target_states,
                        nominal_runtime_ns=nominal_runtime_ns,
                        batch_duration_ns=batch_duration_ns,
                        factories=factories,
                        phase_policy=str(phase_policy),
                        output_states_per_successful_batch=int(
                            protocol["output_states_per_batch"]
                        ),
                        batch_success_probability=float(
                            protocol["batch_success_probability"]
                        ),
                        capacity_states=capacity,
                    )
                    risk = kernel.probability_any_starvation(
                        initial_buffer_states=initial_states
                    )

                    risk_for_log = max(
                        risk,
                        float(np.finfo(float).tiny),
                    )
                    log10_risk = math.log10(risk_for_log)

                    physical_qubits = int(
                        round(total_tiles * tile_factor * distance**2)
                    )
                    campaign_runtime = (
                        nominal_runtime_seconds
                        + float(startup["conservative_startup_seconds"])
                    )

                    candidates.append(
                        {
                            "candidate_id": candidate_id,
                            "factory_count": factories,
                            "buffer_capacity_states": capacity,
                            "initial_buffer_states": initial_states,
                            "phase_policy": phase_policy,
                            "event_order": kernel.event_order,
                            "event_interval_ns": kernel.event_interval_ns,
                            "service_period_events": (
                                kernel.service_period_events
                            ),
                            "total_tiles": total_tiles,
                            "storage_tiles": storage_tiles,
                            "code_distance": distance,
                            "physical_qubits": physical_qubits,
                            "expected_prefill_seconds": startup[
                                "expected_prefill_seconds"
                            ],
                            "phase_setup_seconds": startup[
                                "phase_setup_seconds"
                            ],
                            "conservative_startup_seconds": startup[
                                "conservative_startup_seconds"
                            ],
                            "startup_accounting_model": startup[
                                "startup_accounting_model"
                            ],
                            "successful_prefill_batches_required": startup[
                                "successful_prefill_batches_required"
                            ],
                            "probability_any_starvation": risk,
                            "log10_probability_any_starvation": log10_risk,
                            "risk_probability_underflowed": risk == 0.0,
                            "conservative_campaign_failure_budget": (
                                campaign_failure
                            ),
                            "nominal_campaign_stv_qubit_seconds": (
                                space_time_volume(
                                    physical_qubits=physical_qubits,
                                    runtime_seconds=campaign_runtime,
                                )
                            ),
                        }
                    )

    objectives = [
        Objective(
            metric=str(item["metric"]),
            direction=str(item["direction"]),
        )
        for item in search_cfg["objectives"]
    ]

    frontier, dominated = pareto_partition(candidates, objectives)
    frontier_ids = {str(row["candidate_id"]) for row in frontier}
    dominated_by = {
        str(row["candidate_id"]): row["dominated_by"]
        for row in dominated
    }

    all_candidates: list[dict[str, object]] = []
    for row in candidates:
        enriched = dict(row)
        candidate_id = str(row["candidate_id"])
        enriched["is_pareto"] = candidate_id in frontier_ids
        enriched["dominated_by"] = dominated_by.get(candidate_id, [])
        all_candidates.append(enriched)

    frontier = sorted(
        frontier,
        key=lambda row: (
            int(row["physical_qubits"]),
            float(row["conservative_startup_seconds"]),
            float(row["probability_any_starvation"]),
        ),
    )
    all_candidates = sorted(
        all_candidates,
        key=lambda row: (
            int(row["physical_qubits"]),
            int(row["factory_count"]),
            int(row["buffer_capacity_states"]),
            float(row["conservative_startup_seconds"]),
            str(row["phase_policy"]),
            int(row["initial_buffer_states"]),
        ),
    )

    risk_target_views: dict[str, dict[str, object] | None] = {}
    for target in search_cfg["risk_target_views"]:
        target = float(target)
        reference = _reference_for_risk_target(
            frontier,
            max_starvation_probability=target,
        )
        risk_target_views[f"{target:.10g}"] = (
            None
            if reference is None
            else {
                "candidate_id": reference["candidate_id"],
                "factory_count": reference["factory_count"],
                "buffer_capacity_states": reference[
                    "buffer_capacity_states"
                ],
                "initial_buffer_states": reference[
                    "initial_buffer_states"
                ],
                "phase_policy": reference["phase_policy"],
                "physical_qubits": reference["physical_qubits"],
                "conservative_startup_seconds": reference[
                    "conservative_startup_seconds"
                ],
                "probability_any_starvation": reference[
                    "probability_any_starvation"
                ],
            }
        )

    return {
        "scope": resource["scope"],
        "model": search_cfg["model"],
        "event_order": search_cfg["event_order"],
        "layout_model": resource["multi_factory_layout"]["model"],
        "routing_interconnect_status": resource[
            "multi_factory_layout"
        ]["routing_interconnect"],
        "candidate_count": len(candidates) + len(infeasible),
        "feasible_candidate_count": len(candidates),
        "infeasible_candidate_count": len(infeasible),
        "pareto_candidate_count": len(frontier),
        "objectives": [
            {
                "metric": objective.metric,
                "direction": objective.direction,
            }
            for objective in objectives
        ],
        "feasible_candidates": all_candidates,
        "pareto_frontier": frontier,
        "infeasible_candidates": infeasible,
        "risk_target_views": risk_target_views,
        "reference_selection_rule": search_cfg[
            "reference_selection"
        ]["rule"],
    }


def write_outputs(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_path = output_path / "multi_factory_pareto.json"
    candidates_path = output_path / "multi_factory_candidates.csv"
    frontier_path = output_path / "multi_factory_pareto.csv"

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
                writer.writerow(
                    {key: row.get(key) for key in fieldnames}
                )

    return {
        "json": str(json_path),
        "candidates_csv": str(candidates_path),
        "pareto_csv": str(frontier_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_multi_factory_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/multi_factory_pareto",
    )
    args = parser.parse_args()

    result = run(args.config)
    outputs = write_outputs(result, output_dir=args.output_dir)
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
                "outputs": outputs,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
