from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from simulator.backpressure_network import (
    FiniteBufferBackpressureNetwork,
)
from simulator.buffer_consumer import replicated_storage_tiles
from simulator.config import load_config
from simulator.floorplanner import build_greedy_floorplan
from simulator.interconnect_dynamics import factory_paths_from_floorplan


def _build_event_schedule(
    *,
    event_count: int,
    event_interval_ticks: int,
    factories: int,
    phase_policy: str,
) -> dict[int, tuple[tuple[int, int], ...]]:
    schedule: dict[int, tuple[tuple[int, int], ...]] = {}

    for event_index in range(event_count):
        tick = event_index * event_interval_ticks

        if phase_policy == "synchronized":
            events = tuple(
                (event_index, factory_id)
                for factory_id in range(1, factories + 1)
            )
        elif phase_policy == "even_staggered":
            events = (
                (event_index, (event_index % factories) + 1),
            )
        else:
            raise ValueError(
                f"unsupported phase_policy: {phase_policy}"
            )

        schedule[tick] = events

    return schedule


def _run_scenario(
    *,
    config: dict[str, object],
    scenario: dict[str, object],
    intermediate_capacity: int,
) -> dict[str, object]:
    protocol = config["factories"]["protocol"]
    resource = config["resource_model"]
    stress = config["finite_buffer_network_stress"]

    factories = int(scenario["factory_count"])
    buffer_capacity = int(scenario["buffer_capacity_states"])
    phase_policy = str(scenario["phase_policy"])
    hop_latency_logical_steps = int(
        scenario["hop_latency_logical_steps"]
    )

    buffer_cfg = resource["shared_buffer"]
    storage_tiles = replicated_storage_tiles(
        buffer_capacity_states=buffer_capacity,
        base_capacity_states=int(
            buffer_cfg["base_capacity_states"]
        ),
        base_storage_tiles=int(
            buffer_cfg["base_storage_tiles"]
        ),
    )

    floor_cfg = resource["floorplanner"]
    floorplan = build_greedy_floorplan(
        factory_count=factories,
        data_block_tiles=int(
            resource["data_block"]["tiles"]["value"]
        ),
        shared_buffer_tiles=storage_tiles,
        factory_tiles=int(protocol["distillation_tiles"]),
        clearance_tiles=int(floor_cfg["clearance_tiles"]),
        search_margin_tiles=int(
            floor_cfg["search_margin_tiles"]
        ),
    )
    paths = factory_paths_from_floorplan(floorplan)

    if phase_policy == "synchronized":
        ticks_per_logical_step = 1
        event_interval_ticks = int(
            protocol["protocol_steps_per_batch"]
        )
    else:
        ticks_per_logical_step = factories
        event_interval_ticks = int(
            protocol["protocol_steps_per_batch"]
        )

    hop_latency_ticks = (
        hop_latency_logical_steps * ticks_per_logical_step
    )

    event_count = int(stress["event_count"])
    event_schedule = _build_event_schedule(
        event_count=event_count,
        event_interval_ticks=event_interval_ticks,
        factories=factories,
        phase_policy=phase_policy,
    )
    generation_horizon_end_tick = (
        event_count * event_interval_ticks
    )

    network = FiniteBufferBackpressureNetwork(
        factory_paths=paths,
        injection_queue_capacity_states=int(
            stress["injection_queue_capacity_states"]
        ),
        intermediate_queue_capacity_states=intermediate_capacity,
        injection_bandwidth_states_per_tick=int(
            stress["injection_bandwidth_states_per_tick"]
        ),
        hop_latency_ticks=hop_latency_ticks,
    )

    max_drain_ticks = (
        int(stress["max_drain_factory_periods"])
        * int(protocol["protocol_steps_per_batch"])
        * ticks_per_logical_step
    )

    summary = network.run(
        event_schedule=event_schedule,
        generation_horizon_end_tick=generation_horizon_end_tick,
        states_per_batch=int(
            protocol["output_states_per_batch"]
        ),
        max_drain_ticks=max_drain_ticks,
    )

    route_counts = Counter(
        cell
        for path in paths.values()
        for cell in path
    )
    shared_route_cells = sum(
        count > 1 for count in route_counts.values()
    )

    scheduled = summary.scheduled_factory_events
    generated_fraction = (
        summary.generated_batches / scheduled
        if scheduled
        else 0.0
    )

    return {
        "scenario": scenario["name"],
        "factory_count": factories,
        "buffer_capacity_states": buffer_capacity,
        "phase_policy": phase_policy,
        "event_count": event_count,
        "success_mode": stress["success_mode"],
        "ticks_per_logical_step": ticks_per_logical_step,
        "event_interval_ticks": event_interval_ticks,
        "event_interval_logical_steps": (
            event_interval_ticks / ticks_per_logical_step
        ),
        "hop_latency_logical_steps": (
            hop_latency_logical_steps
        ),
        "hop_latency_ticks": hop_latency_ticks,
        "intermediate_queue_capacity_states": (
            intermediate_capacity
        ),
        "injection_queue_capacity_states": int(
            stress["injection_queue_capacity_states"]
        ),
        "injection_bandwidth_states_per_tick": int(
            stress["injection_bandwidth_states_per_tick"]
        ),
        "route_lengths_cells": {
            str(factory_id): len(path)
            for factory_id, path in sorted(paths.items())
        },
        "shared_route_cells": shared_route_cells,
        "scheduled_factory_events": scheduled,
        "generated_batches": summary.generated_batches,
        "suppressed_factory_events": (
            summary.suppressed_factory_events
        ),
        "generated_batch_fraction": generated_fraction,
        "generated_states": summary.generated_states,
        "delivered_states": summary.delivered_states,
        "all_generated_states_delivered": (
            summary.all_generated_states_delivered
        ),
        "max_network_states": summary.max_network_states,
        "max_injection_queue_occupancy": (
            summary.max_injection_queue_occupancy
        ),
        "max_intermediate_queue_occupancy": (
            summary.max_intermediate_queue_occupancy
        ),
        "injection_queue_full_ticks": (
            summary.injection_queue_full_ticks
        ),
        "intermediate_queue_full_ticks": (
            summary.intermediate_queue_full_ticks
        ),
        "factory_output_backpressure_ticks": (
            summary.factory_output_backpressure_ticks
        ),
        "blocked_after_service_ticks": (
            summary.blocked_after_service_ticks
        ),
        "blocked_after_service_cell_logical_steps": (
            summary.blocked_after_service_ticks
            / ticks_per_logical_step
        ),
        "max_carryover_batches_at_event_boundary": (
            summary.max_carryover_batches_at_event_boundary
        ),
        "event_boundaries_with_carryover": (
            summary.event_boundaries_with_carryover
        ),
        "fraction_event_boundaries_with_carryover": (
            summary.fraction_event_boundaries_with_carryover
        ),
        "mean_batch_latency_logical_steps": (
            summary.mean_batch_latency_ticks
            / ticks_per_logical_step
        ),
        "p95_batch_latency_logical_steps": (
            summary.p95_batch_latency_ticks
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
        "busiest_cell_utilization_during_generation_horizon": (
            summary.busiest_cell_utilization_during_generation_horizon
        ),
        "total_cell_busy_logical_steps": (
            summary.total_cell_busy_ticks
            / ticks_per_logical_step
        ),
    }


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    stress = config["finite_buffer_network_stress"]

    rows: list[dict[str, object]] = []
    for scenario in stress["scenarios"]:
        for capacity in stress[
            "intermediate_queue_capacity_states"
        ]:
            rows.append(
                _run_scenario(
                    config=config,
                    scenario=scenario,
                    intermediate_capacity=int(capacity),
                )
            )

    return {
        "scope": config["resource_model"]["scope"],
        "model": stress["model"],
        "source": stress["source"],
        "success_mode": stress["success_mode"],
        "row_count": len(rows),
        "results": rows,
    }


def write_outputs(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_path = output_path / "finite_buffer_backpressure.json"
    csv_path = output_path / "finite_buffer_backpressure.csv"

    json_path.write_text(
        json.dumps(result, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    rows = list(result["results"])
    fieldnames = sorted(
        {
            key
            for row in rows
            for key in row.keys()
            if key != "route_lengths_cells"
        }
    )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
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
        "csv": str(csv_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=(
            "configs/"
            "litinski_finite_buffer_backpressure_stress.yaml"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="results/finite_buffer_backpressure",
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
                "summary": {
                    "row_count": result["row_count"],
                    "success_mode": result["success_mode"],
                },
                "outputs": outputs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
