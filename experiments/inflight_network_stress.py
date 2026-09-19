from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from simulator.buffer_consumer import replicated_storage_tiles
from simulator.config import load_config
from simulator.floorplanner import build_greedy_floorplan
from simulator.inflight_network import PersistentReservationNetwork
from simulator.interconnect_dynamics import factory_paths_from_floorplan


def _run_scenario(
    *,
    config: dict[str, object],
    scenario: dict[str, object],
    hop_latency_logical_steps: int,
) -> dict[str, object]:
    protocol = config["factories"]["protocol"]
    resource = config["resource_model"]
    stress = config["inflight_network_stress"]

    factories = int(scenario["factory_count"])
    capacity = int(scenario["buffer_capacity_states"])
    phase_policy = str(scenario["phase_policy"])

    if phase_policy not in ("synchronized", "even_staggered"):
        raise ValueError(f"unsupported phase_policy: {phase_policy}")

    buffer_cfg = resource["shared_buffer"]
    storage_tiles = replicated_storage_tiles(
        buffer_capacity_states=capacity,
        base_capacity_states=int(buffer_cfg["base_capacity_states"]),
        base_storage_tiles=int(buffer_cfg["base_storage_tiles"]),
    )

    floor_cfg = resource["floorplanner"]
    floorplan = build_greedy_floorplan(
        factory_count=factories,
        data_block_tiles=int(resource["data_block"]["tiles"]["value"]),
        shared_buffer_tiles=storage_tiles,
        factory_tiles=int(protocol["distillation_tiles"]),
        clearance_tiles=int(floor_cfg["clearance_tiles"]),
        search_margin_tiles=int(floor_cfg["search_margin_tiles"]),
    )
    paths = factory_paths_from_floorplan(floorplan)

    if phase_policy == "synchronized":
        ticks_per_logical_step = 1
        event_interval_ticks = int(protocol["protocol_steps_per_batch"])
    else:
        ticks_per_logical_step = factories
        event_interval_ticks = int(protocol["protocol_steps_per_batch"])

    hop_latency_ticks = (
        hop_latency_logical_steps * ticks_per_logical_step
    )

    network = PersistentReservationNetwork(
        factory_paths=paths,
        lane_capacity_states_per_tick=int(
            stress["lane_capacity_states_per_tick"]
        ),
        hop_latency_ticks=hop_latency_ticks,
    )

    event_count = int(stress["event_count"])
    event_ticks: list[int] = []

    for event_index in range(event_count):
        tick = event_index * event_interval_ticks
        event_ticks.append(tick)

        if phase_policy == "synchronized":
            active_factories = tuple(range(1, factories + 1))
        else:
            active_factories = ((event_index % factories) + 1,)

        batches = tuple(
            (
                f"{scenario['name']}_E{event_index:06d}_F{factory_id}",
                factory_id,
                int(protocol["output_states_per_batch"]),
            )
            for factory_id in active_factories
        )

        network.enqueue_simultaneous_batches(
            generation_tick=tick,
            batches=batches,
        )

    generation_horizon_end_tick = event_count * event_interval_ticks
    summary = network.summarize(
        event_ticks=event_ticks,
        generation_horizon_end_tick=generation_horizon_end_tick,
    )

    return {
        "scenario": scenario["name"],
        "factory_count": factories,
        "buffer_capacity_states": capacity,
        "phase_policy": phase_policy,
        "event_count": event_count,
        "success_mode": stress["success_mode"],
        "ticks_per_logical_step": ticks_per_logical_step,
        "event_interval_ticks": event_interval_ticks,
        "hop_latency_logical_steps": hop_latency_logical_steps,
        "hop_latency_ticks": hop_latency_ticks,
        "route_lengths_cells": {
            str(factory_id): len(path)
            for factory_id, path in sorted(paths.items())
        },
        "generated_batches": summary.generated_batches,
        "generated_states": summary.generated_states,
        "max_inflight_batches_at_event_boundary": (
            summary.max_inflight_batches_at_event_boundary
        ),
        "event_boundaries_with_inflight": (
            summary.event_boundaries_with_inflight
        ),
        "fraction_event_boundaries_with_inflight": (
            summary.fraction_event_boundaries_with_inflight
        ),
        "inflight_batches_after_last_generation": (
            summary.inflight_batches_after_last_generation
        ),
        "drain_tail_ticks": summary.drain_tail_ticks,
        "drain_tail_logical_steps": (
            summary.drain_tail_ticks / ticks_per_logical_step
        ),
        "mean_batch_latency_ticks": summary.mean_batch_latency_ticks,
        "mean_batch_latency_logical_steps": (
            summary.mean_batch_latency_ticks / ticks_per_logical_step
        ),
        "p95_batch_latency_logical_steps": (
            summary.p95_batch_latency_ticks / ticks_per_logical_step
        ),
        "max_batch_latency_logical_steps": (
            summary.max_batch_latency_ticks / ticks_per_logical_step
        ),
        "mean_contention_wait_logical_steps_per_state": (
            summary.mean_contention_wait_ticks_per_state
            / ticks_per_logical_step
        ),
        "max_contention_wait_logical_steps_per_state": (
            summary.max_contention_wait_ticks_per_state
            / ticks_per_logical_step
        ),
        "busiest_cell_reserved_ticks": summary.busiest_cell_reserved_ticks,
        "busiest_cell_utilization_during_generation_horizon": (
            summary.busiest_cell_utilization_during_generation_horizon
        ),
        "total_reserved_cell_ticks": summary.total_reserved_cell_ticks,
    }


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    stress = config["inflight_network_stress"]

    rows: list[dict[str, object]] = []
    for scenario in stress["scenarios"]:
        for hop_latency in stress["hop_latency_logical_steps"]:
            rows.append(
                _run_scenario(
                    config=config,
                    scenario=scenario,
                    hop_latency_logical_steps=int(hop_latency),
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

    json_path = output_path / "inflight_network_stress.json"
    csv_path = output_path / "inflight_network_stress.csv"

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
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: row.get(key) for key in fieldnames}
            )

    return {"json": str(json_path), "csv": str(csv_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_inflight_network_stress.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/inflight_network_stress",
    )
    args = parser.parse_args()

    result = run(args.config)
    outputs = write_outputs(result, output_dir=args.output_dir)
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
