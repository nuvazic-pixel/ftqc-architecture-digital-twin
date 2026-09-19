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
from simulator.floorplanner import build_greedy_floorplan
from simulator.interconnect_dynamics import (
    InterconnectDynamicsError,
    analyze_transport_aware_starvation,
)
from simulator.multi_factory import multi_factory_startup_cost
from simulator.system_reliability import logical_failure_budget_from_runtime


def _candidate_id(
    *,
    factories: int,
    capacity: int,
    phase_policy: str,
    initial_states: int,
) -> str:
    phase = "SYNC" if phase_policy == "synchronized" else "STAG"
    return f"N{factories}_B{capacity:03d}_{phase}_I{initial_states:03d}"


def _reference_for_risk_target(
    candidates: list[dict[str, object]],
    *,
    max_starvation_probability: float,
) -> dict[str, object] | None:
    eligible = [
        row
        for row in candidates
        if float(row["probability_any_starvation"])
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


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)

    protocol = config["factories"]["protocol"]
    resource = config["resource_model"]
    search_cfg = config["multi_factory_search"]
    transport_cfg = config["interconnect_dynamics"]
    qec = config["qec"]

    target_states = int(config["workload"]["t_count"])
    nominal_runtime_seconds = float(
        search_cfg["consumer"]["nominal_runtime_seconds"]
    )
    nominal_runtime_ns = int(round(nominal_runtime_seconds * 1e9))
    code_cycle_ns = int(
        config["hardware"]["timing_ns"]["code_cycle"]["value"]
    )
    code_cycle_seconds = code_cycle_ns * 1e-9

    tile_factor = float(
        resource["tile_model"]["physical_qubits_per_d2"]["value"]
    )
    data_tiles = int(resource["data_block"]["tiles"]["value"])
    buffer_cfg = resource["shared_buffer"]
    floor_cfg = resource["floorplanner"]
    max_failure = float(
        search_cfg["feasibility"][
            "max_conservative_campaign_failure_budget"
        ]
    )

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
                    buffer_cfg["base_capacity_states"]
                ),
                base_storage_tiles=int(
                    buffer_cfg["base_storage_tiles"]
                ),
            )

            floorplan = build_greedy_floorplan(
                factory_count=factories,
                data_block_tiles=data_tiles,
                shared_buffer_tiles=storage_tiles,
                factory_tiles=int(protocol["distillation_tiles"]),
                clearance_tiles=int(floor_cfg["clearance_tiles"]),
                search_margin_tiles=int(floor_cfg["search_margin_tiles"]),
            )
            baseline = build_greedy_floorplan(
                factory_count=int(
                    floor_cfg["embedded_baseline_factory_count"]
                ),
                data_block_tiles=data_tiles,
                shared_buffer_tiles=storage_tiles,
                factory_tiles=int(protocol["distillation_tiles"]),
                clearance_tiles=int(floor_cfg["clearance_tiles"]),
                search_margin_tiles=int(floor_cfg["search_margin_tiles"]),
            )

            routing_tiles = max(
                0,
                floorplan.route_union_tiles - baseline.route_union_tiles,
            )
            base_architecture_tiles = (
                data_tiles
                + factories * int(protocol["distillation_tiles"])
                + storage_tiles
            )
            total_tiles = base_architecture_tiles + routing_tiles

            for initial_states in search_cfg["sensitivity"][
                "initial_buffer_states"
            ]:
                initial_states = int(initial_states)
                if initial_states > capacity:
                    continue

                for phase_policy in phase_policies:
                    phase_policy = str(phase_policy)
                    candidate_id = _candidate_id(
                        factories=factories,
                        capacity=capacity,
                        phase_policy=phase_policy,
                        initial_states=initial_states,
                    )

                    chosen: dict[str, object] | None = None
                    last_reason: str | None = None

                    for distance_raw in qec["allowed_distances"]:
                        distance = int(distance_raw)
                        logical_step_ns = distance * code_cycle_ns
                        batch_duration_ns = (
                            distance
                            * int(protocol["protocol_steps_per_batch"])
                            * code_cycle_ns
                        )
                        batch_duration_seconds = (
                            batch_duration_ns / 1_000_000_000
                        )

                        startup = multi_factory_startup_cost(
                            initial_buffer_states=initial_states,
                            factories=factories,
                            phase_policy=phase_policy,
                            batch_duration_seconds=batch_duration_seconds,
                            output_states_per_successful_batch=int(
                                protocol["output_states_per_batch"]
                            ),
                            batch_success_probability=float(
                                protocol["batch_success_probability"]
                            ),
                        )

                        # Transport delay/stalls can only increase campaign
                        # duration. If this cheaper lower-bound campaign already
                        # fails reliability, there is no reason to build the
                        # expensive exact transport kernel at this distance.
                        lower_bound_failure = logical_failure_budget_from_runtime(
                            tile_count=total_tiles,
                            runtime_seconds=(
                                nominal_runtime_seconds
                                + startup.conservative_startup_seconds
                            ),
                            code_cycle_time_seconds=code_cycle_seconds,
                            distance=distance,
                            physical_error=config["hardware"]["errors"][
                                "p_2q"
                            ]["value"],
                            physical_error_threshold=qec[
                                "physical_error_threshold"
                            ]["value"],
                            fit_A=qec["fit_A"]["value"],
                        )
                        if lower_bound_failure > max_failure:
                            last_reason = (
                                "lower-bound campaign already exceeds logical "
                                "failure budget before transport dynamics."
                            )
                            continue

                        try:
                            transport = analyze_transport_aware_starvation(
                                floorplan=floorplan,
                                target_states=target_states,
                                nominal_runtime_ns=nominal_runtime_ns,
                                batch_duration_ns=batch_duration_ns,
                                factories=factories,
                                phase_policy=phase_policy,
                                output_states_per_batch=int(
                                    protocol["output_states_per_batch"]
                                ),
                                batch_success_probability=float(
                                    protocol["batch_success_probability"]
                                ),
                                capacity_states=capacity,
                                initial_buffer_states=initial_states,
                                logical_step_ns=logical_step_ns,
                                lane_capacity_states_per_logical_step=int(
                                    transport_cfg[
                                        "lane_capacity_states_per_logical_step"
                                    ]
                                ),
                            )
                        except InterconnectDynamicsError as exc:
                            last_reason = str(exc)
                            continue

                        if phase_policy == "synchronized":
                            transport_tail_ns = (
                                transport.max_all_success_transport_latency_ns
                            )
                        else:
                            transport_tail_ns = (
                                transport.max_single_batch_transport_latency_ns
                            )

                        transport_tail_seconds = (
                            transport_tail_ns / 1_000_000_000
                        )
                        conservative_startup = (
                            startup.conservative_startup_seconds
                            + transport_tail_seconds
                        )
                        expected_execution_runtime = (
                            nominal_runtime_seconds
                            + transport.expected_stall_extension_seconds
                        )
                        expected_campaign_wall_time = (
                            conservative_startup
                            + expected_execution_runtime
                        )

                        failure = logical_failure_budget_from_runtime(
                            tile_count=total_tiles,
                            runtime_seconds=expected_campaign_wall_time,
                            code_cycle_time_seconds=code_cycle_seconds,
                            distance=distance,
                            physical_error=config["hardware"]["errors"][
                                "p_2q"
                            ]["value"],
                            physical_error_threshold=qec[
                                "physical_error_threshold"
                            ]["value"],
                            fit_A=qec["fit_A"]["value"],
                        )

                        if failure > max_failure:
                            last_reason = (
                                "transport-aware expected campaign exceeds "
                                "logical failure budget."
                            )
                            continue

                        physical_qubits = int(
                            round(total_tiles * tile_factor * distance**2)
                        )
                        risk = transport.probability_any_starvation
                        risk_for_log = max(
                            risk,
                            float(np.finfo(float).tiny),
                        )

                        chosen = {
                            "candidate_id": candidate_id,
                            "factory_count": factories,
                            "buffer_capacity_states": capacity,
                            "initial_buffer_states": initial_states,
                            "phase_policy": phase_policy,
                            "code_distance": distance,
                            "storage_tiles": storage_tiles,
                            "base_architecture_tiles": base_architecture_tiles,
                            "routing_tiles": routing_tiles,
                            "total_tiles": total_tiles,
                            "physical_qubits": physical_qubits,
                            "floorplan_total_route_union_tiles": (
                                floorplan.route_union_tiles
                            ),
                            "floorplan_embedded_baseline_route_tiles": (
                                baseline.route_union_tiles
                            ),
                            "floorplan_bbox_area_tiles": (
                                floorplan.bbox_area_tiles
                            ),
                            "floorplan_packing_density": (
                                floorplan.packing_density
                            ),
                            "transport_model": transport_cfg["model"],
                            "lane_capacity_states_per_logical_step": (
                                transport.lane_capacity_states_per_logical_step
                            ),
                            "transport_event_interval_ns": (
                                transport.event_interval_ns
                            ),
                            "transport_service_period_events": (
                                transport.service_period_events
                            ),
                            "max_single_batch_transport_latency_ns": (
                                transport.max_single_batch_transport_latency_ns
                            ),
                            "max_all_success_transport_latency_ns": (
                                transport.max_all_success_transport_latency_ns
                            ),
                            "transport_prefill_tail_seconds": (
                                transport_tail_seconds
                            ),
                            "expected_prefill_seconds": (
                                startup.expected_prefill_seconds
                            ),
                            "phase_setup_seconds": (
                                startup.phase_setup_seconds
                            ),
                            "conservative_startup_seconds": (
                                conservative_startup
                            ),
                            "probability_any_starvation": risk,
                            "log10_probability_any_starvation": (
                                math.log10(risk_for_log)
                            ),
                            "risk_probability_underflowed": risk == 0.0,
                            "expected_starved_service_slots": (
                                transport.expected_starved_service_slots
                            ),
                            "expected_stall_intervals": (
                                transport.expected_stall_intervals
                            ),
                            "expected_overflow_states": (
                                transport.expected_overflow_states
                            ),
                            "expected_stall_extension_seconds": (
                                transport.expected_stall_extension_seconds
                            ),
                            "expected_execution_runtime_seconds": (
                                expected_execution_runtime
                            ),
                            "expected_campaign_wall_time_seconds": (
                                expected_campaign_wall_time
                            ),
                            "conservative_campaign_failure_budget": (
                                failure
                            ),
                            "expected_campaign_stv_qubit_seconds": (
                                space_time_volume(
                                    physical_qubits=physical_qubits,
                                    runtime_seconds=expected_campaign_wall_time,
                                )
                            ),
                            "nominal_no_stall_stv_qubit_seconds": (
                                space_time_volume(
                                    physical_qubits=physical_qubits,
                                    runtime_seconds=(
                                        nominal_runtime_seconds
                                        + conservative_startup
                                    ),
                                )
                            ),
                        }
                        break

                    if chosen is None:
                        infeasible.append(
                            {
                                "candidate_id": candidate_id,
                                "factory_count": factories,
                                "buffer_capacity_states": capacity,
                                "initial_buffer_states": initial_states,
                                "phase_policy": phase_policy,
                                "reason": last_reason
                                or "no allowed code distance passed.",
                            }
                        )
                    else:
                        candidates.append(chosen)

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

    feasible: list[dict[str, object]] = []
    for row in candidates:
        enriched = dict(row)
        candidate_id = str(row["candidate_id"])
        enriched["is_pareto"] = candidate_id in frontier_ids
        enriched["dominated_by"] = dominated_by.get(candidate_id, [])
        feasible.append(enriched)

    frontier = sorted(
        frontier,
        key=lambda row: (
            int(row["physical_qubits"]),
            float(row["conservative_startup_seconds"]),
            float(row["probability_any_starvation"]),
        ),
    )
    feasible = sorted(
        feasible,
        key=lambda row: (
            int(row["physical_qubits"]),
            int(row["factory_count"]),
            int(row["buffer_capacity_states"]),
            str(row["phase_policy"]),
            int(row["initial_buffer_states"]),
        ),
    )

    views: dict[str, dict[str, object] | None] = {}
    for target_raw in search_cfg["risk_target_views"]:
        target = float(target_raw)
        reference = _reference_for_risk_target(
            frontier,
            max_starvation_probability=target,
        )
        views[f"{target:.10g}"] = (
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
                "expected_stall_extension_seconds": reference[
                    "expected_stall_extension_seconds"
                ],
                "expected_campaign_stv_qubit_seconds": reference[
                    "expected_campaign_stv_qubit_seconds"
                ],
            }
        )

    return {
        "scope": resource["scope"],
        "model": search_cfg["model"],
        "transport_model": transport_cfg["model"],
        "transport_source": transport_cfg["source"],
        "candidate_count": len(candidates) + len(infeasible),
        "feasible_candidate_count": len(candidates),
        "infeasible_candidate_count": len(infeasible),
        "pareto_candidate_count": len(frontier),
        "feasible_candidates": feasible,
        "pareto_frontier": frontier,
        "infeasible_candidates": infeasible,
        "risk_target_views": views,
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

    json_path = output_path / "transport_aware_pareto.json"
    candidates_path = output_path / "transport_aware_candidates.csv"
    frontier_path = output_path / "transport_aware_pareto.csv"

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
        default="configs/litinski_multi_factory_transport_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/transport_aware_pareto",
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
                    "infeasible_candidate_count": result[
                        "infeasible_candidate_count"
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
