from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from metrics.pareto import Objective, pareto_partition
from metrics.space_time_volume import space_time_volume
from simulator.backpressure_network import (
    FiniteBufferBackpressureNetwork,
)
from simulator.buffer_consumer import replicated_storage_tiles
from simulator.config import load_config
from simulator.m17_candidate import (
    BeamSearchConfig,
    generate_layout_candidate_specs,
)
from simulator.m17_materializer import materialize_diverse_beam


def _event_schedule(
    *,
    event_count: int,
    event_interval_ticks: int,
    factories: int,
) -> dict[int, tuple[tuple[int, int], ...]]:
    return {
        event_index * event_interval_ticks: (
            (
                event_index,
                (event_index % factories) + 1,
            ),
        )
        for event_index in range(event_count)
    }


def _evaluate_layout(
    *,
    layout,
    config: dict[str, object],
    buffer_capacity_states: int,
) -> dict[str, object]:
    protocol = config["factories"]["protocol"]
    m16 = config["m16_evaluation"]
    hardware = config["hardware"]
    resource = config["resource_model"]

    factories = layout.spec.factory_count
    code_distance = int(m16["fixed_code_distance"])
    code_cycle_ns = int(
        hardware["timing_ns"]["code_cycle"]["value"]
    )
    logical_step_ns = code_distance * code_cycle_ns

    ticks_per_logical_step = factories
    event_interval_ticks = int(
        protocol["protocol_steps_per_batch"]
    )
    hop_latency_ticks = (
        int(m16["hop_latency_logical_steps"])
        * ticks_per_logical_step
    )

    event_count = int(m16["event_count"])
    schedule = _event_schedule(
        event_count=event_count,
        event_interval_ticks=event_interval_ticks,
        factories=factories,
    )
    generation_horizon_end_tick = (
        event_count * event_interval_ticks
    )

    network = FiniteBufferBackpressureNetwork(
        factory_paths=layout.factory_paths,
        injection_queue_capacity_states=int(
            m16["injection_queue_capacity_states"]
        ),
        intermediate_queue_capacity_states=int(
            m16["intermediate_queue_capacity_states"]
        ),
        injection_bandwidth_states_per_tick=int(
            m16["injection_bandwidth_states_per_tick"]
        ),
        hop_latency_ticks=hop_latency_ticks,
    )

    summary = network.run(
        event_schedule=schedule,
        generation_horizon_end_tick=generation_horizon_end_tick,
        states_per_batch=int(
            protocol["output_states_per_batch"]
        ),
        max_drain_ticks=(
            int(m16["max_drain_factory_periods"])
            * int(protocol["protocol_steps_per_batch"])
            * ticks_per_logical_step
        ),
    )

    tick_seconds = (
        logical_step_ns
        / ticks_per_logical_step
        / 1_000_000_000
    )
    stress_wall_clock = (
        generation_horizon_end_tick
        + summary.drain_tail_ticks
    ) * tick_seconds
    blocked_time = (
        summary.blocked_after_service_ticks
        * tick_seconds
    )

    physical_qubits_per_d2 = float(
        resource["tile_model"][
            "physical_qubits_per_d2"
        ]
    )
    physical_qubits = int(
        round(
            layout.floorplan.active_tiles
            * physical_qubits_per_d2
            * code_distance**2
        )
    )

    suppressed_states = (
        summary.suppressed_factory_events
        * int(protocol["output_states_per_batch"])
    )
    scheduled_states = (
        summary.scheduled_factory_events
        * int(protocol["output_states_per_batch"])
    )

    row = layout.to_dict()
    row.update(
        {
            "evaluation_scope": m16["temporal_scope"],
            "success_mode": m16["success_mode"],
            "phase_policy": m16["phase_policy"],
            "code_distance": code_distance,
            "buffer_capacity_states": buffer_capacity_states,
            "physical_qubits": physical_qubits,
            "scheduled_factory_events": (
                summary.scheduled_factory_events
            ),
            "generated_batches": summary.generated_batches,
            "suppressed_factory_events": (
                summary.suppressed_factory_events
            ),
            "suppressed_output_states": suppressed_states,
            "production_shortfall_fraction": (
                suppressed_states / scheduled_states
                if scheduled_states
                else 0.0
            ),
            "blocked_time_seconds": blocked_time,
            "blocked_after_service_ticks": (
                summary.blocked_after_service_ticks
            ),
            "max_network_states": summary.max_network_states,
            "max_carryover_batches_at_event_boundary": (
                summary.max_carryover_batches_at_event_boundary
            ),
            "fraction_event_boundaries_with_carryover": (
                summary.fraction_event_boundaries_with_carryover
            ),
            "mean_batch_latency_logical_steps": (
                summary.mean_batch_latency_ticks
                / ticks_per_logical_step
            ),
            "max_batch_latency_logical_steps": (
                summary.max_batch_latency_ticks
                / ticks_per_logical_step
            ),
            "drain_tail_logical_steps": (
                summary.drain_tail_ticks
                / ticks_per_logical_step
            ),
            "stress_wall_clock_seconds": stress_wall_clock,
            "stress_space_time_volume": space_time_volume(
                physical_qubits=physical_qubits,
                runtime_seconds=stress_wall_clock,
            ),
            "busiest_cell_utilization": (
                summary.busiest_cell_utilization_during_generation_horizon
            ),
            "all_generated_states_delivered": (
                summary.all_generated_states_delivered
            ),
            "starvation_probability": None,
            "starvation_probability_status": (
                m16["starvation_probability_status"]
            ),
        }
    )
    return row


def _sharing_sweep(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    degrees = sorted(
        {float(row["corridor_sharing_degree"]) for row in rows}
    )
    result = []

    for degree in degrees:
        group = [
            row
            for row in rows
            if float(row["corridor_sharing_degree"]) == degree
        ]
        result.append(
            {
                "corridor_sharing_degree": degree,
                "candidate_count": len(group),
                "min_physical_qubits": min(
                    int(row["physical_qubits"])
                    for row in group
                ),
                "min_stress_space_time_volume": min(
                    float(row["stress_space_time_volume"])
                    for row in group
                ),
                "max_actual_route_overlap_fraction": max(
                    float(row["actual_route_overlap_fraction"])
                    for row in group
                ),
                "max_shared_factory_route_cells": max(
                    int(row["shared_factory_route_cells"])
                    for row in group
                ),
                "max_blocked_time_seconds": max(
                    float(row["blocked_time_seconds"])
                    for row in group
                ),
                "max_suppressed_factory_events": max(
                    int(row["suppressed_factory_events"])
                    for row in group
                ),
                "backpressure_candidate_count": sum(
                    int(row["blocked_after_service_ticks"]) > 0
                    or int(row["suppressed_factory_events"]) > 0
                    for row in group
                ),
            }
        )

    return result


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    m17 = config["m17_floorplanner"]
    resource = config["resource_model"]
    buffer_cfg = resource["shared_buffer"]

    beam_config = BeamSearchConfig(
        beam_width=int(m17["beam_width"]),
        sharing_degrees=tuple(
            float(x)
            for x in m17["corridor_sharing_degrees"]
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

    rows: list[dict[str, object]] = []
    beam_survivors: dict[str, list[str]] = {}

    for factory_count_raw in m17["factory_counts"]:
        factory_count = int(factory_count_raw)
        specs = generate_layout_candidate_specs(
            factory_count=factory_count,
            config=beam_config,
        )

        capacity_map = buffer_cfg[
            "buffer_capacity_by_factory_count"
        ]
        buffer_capacity = int(
            capacity_map.get(
                factory_count,
                capacity_map.get(str(factory_count)),
            )
        )
        storage_tiles = replicated_storage_tiles(
            buffer_capacity_states=buffer_capacity,
            base_capacity_states=int(
                buffer_cfg["base_capacity_states"]
            ),
            base_storage_tiles=int(
                buffer_cfg["base_storage_tiles"]
            ),
        )

        layouts = materialize_diverse_beam(
            specs=specs,
            data_block_tiles=int(
                resource["data_block_tiles"]
            ),
            shared_buffer_tiles=storage_tiles,
            factory_tiles=int(
                config["factories"]["protocol"][
                    "distillation_tiles"
                ]
            ),
            beam_width=int(m17["beam_width"]),
            search_margin_tiles=int(
                m17["search_margin_tiles"]
            ),
        )

        beam_survivors[str(factory_count)] = [
            layout.spec.candidate_id
            for layout in layouts
        ]

        for layout in layouts:
            rows.append(
                _evaluate_layout(
                    layout=layout,
                    config=config,
                    buffer_capacity_states=buffer_capacity,
                )
            )

    objectives = [
        Objective(
            metric=str(metric),
            direction="min",
        )
        for metric in config["optimizer"]["pareto_metrics"]
    ]
    frontier, dominated = pareto_partition(
        rows,
        objectives,
    )

    dominated_by = {
        str(row["candidate_id"]): row["dominated_by"]
        for row in dominated
    }
    frontier_ids = {
        str(row["candidate_id"])
        for row in frontier
    }

    annotated = []
    for row in rows:
        item = dict(row)
        candidate_id = str(row["candidate_id"])
        item["is_pareto"] = candidate_id in frontier_ids
        item["dominated_by"] = dominated_by.get(
            candidate_id,
            [],
        )
        annotated.append(item)

    sweep = _sharing_sweep(annotated)
    tipping = next(
        (
            item["corridor_sharing_degree"]
            for item in sweep
            if int(item["backpressure_candidate_count"]) > 0
        ),
        None,
    )

    return {
        "milestone": "M17B",
        "phase": "beam_materialize_and_m16_evaluate",
        "candidate_count": len(annotated),
        "pareto_candidate_count": len(frontier),
        "beam_survivors": beam_survivors,
        "candidates": sorted(
            annotated,
            key=lambda row: (
                int(row["factory_count"]),
                float(row["corridor_sharing_degree"]),
                int(row["physical_qubits"]),
                str(row["candidate_id"]),
            ),
        ),
        "pareto_frontier": sorted(
            frontier,
            key=lambda row: (
                int(row["physical_qubits"]),
                float(row["stress_space_time_volume"]),
                str(row["candidate_id"]),
            ),
        ),
        "corridor_sharing_sweep": sweep,
        "first_backpressure_sharing_degree": tipping,
        "starvation_probability_status": (
            config["m16_evaluation"][
                "starvation_probability_status"
            ]
        ),
        "scientific_scope": (
            "Deterministic all-success stress-horizon co-design. "
            "Run-level starvation probability is deferred to M18."
        ),
    }


def write_outputs(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    json_path = output / "m17b_results.json"
    csv_path = output / "m17b_candidates.csv"
    pareto_path = output / "m17b_pareto.csv"

    json_path.write_text(
        json.dumps(result, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    candidates = list(result["candidates"])
    frontier = list(result["pareto_frontier"])
    fieldnames = sorted(
        {
            key
            for row in (*candidates, *frontier)
            for key in row
            if key not in (
                "placements",
                "routes",
                "dominated_by",
            )
        }
    )

    for path, rows in (
        (csv_path, candidates),
        (pareto_path, frontier),
    ):
        with path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: row.get(key)
                        for key in fieldnames
                    }
                )

    return {
        "json": str(json_path),
        "candidates_csv": str(csv_path),
        "pareto_csv": str(pareto_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/m17b_beam_materializer.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/m17b",
    )
    args = parser.parse_args()

    result = run(args.config)
    outputs = write_outputs(
        result,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "pareto_candidate_count": (
                    result["pareto_candidate_count"]
                ),
                "first_backpressure_sharing_degree": (
                    result[
                        "first_backpressure_sharing_degree"
                    ]
                ),
                "outputs": outputs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
