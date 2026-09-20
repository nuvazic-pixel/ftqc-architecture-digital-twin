from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from metrics.pareto import Objective, pareto_partition
from simulator.backpressure_network import (
    FiniteBufferBackpressureNetwork,
)
from simulator.beam_floorplanner import (
    LayoutCandidate,
    candidate_summary,
    generate_layout_candidates,
)
from simulator.buffer_consumer import replicated_storage_tiles
from simulator.config import load_config
from simulator.interconnect_dynamics import (
    factory_paths_from_floorplan,
)


def _event_schedule(
    *,
    event_count: int,
    event_interval_ticks: int,
    factories: int,
    phase_policy: str,
) -> dict[int, tuple[tuple[int, int], ...]]:
    schedule: dict[int, tuple[tuple[int, int], ...]] = {}

    for event_index in range(event_count):
        tick = event_index * event_interval_ticks
        if phase_policy == "even_staggered":
            events = (
                (event_index, (event_index % factories) + 1),
            )
        elif phase_policy == "synchronized":
            events = tuple(
                (event_index, factory_id)
                for factory_id in range(1, factories + 1)
            )
        else:
            raise ValueError(
                f"unsupported phase_policy: {phase_policy}"
            )
        schedule[tick] = events

    return schedule


def _evaluate_network(
    *,
    candidate: LayoutCandidate,
    protocol: dict[str, object],
    stress: dict[str, object],
    phase_policy: str,
    hop_latency_logical_steps: int,
) -> dict[str, object]:
    factories = candidate.factory_count
    paths = factory_paths_from_floorplan(
        candidate.floorplan
    )

    if phase_policy == "even_staggered":
        ticks_per_logical_step = factories
        event_interval_ticks = int(
            protocol["protocol_steps_per_batch"]
        )
    else:
        ticks_per_logical_step = 1
        event_interval_ticks = int(
            protocol["protocol_steps_per_batch"]
        )

    hop_latency_ticks = (
        hop_latency_logical_steps
        * ticks_per_logical_step
    )
    event_count = int(stress["event_count"])
    generation_horizon_end_tick = (
        event_count * event_interval_ticks
    )

    network = FiniteBufferBackpressureNetwork(
        factory_paths=paths,
        injection_queue_capacity_states=int(
            stress["injection_queue_capacity_states"]
        ),
        intermediate_queue_capacity_states=int(
            stress["intermediate_queue_capacity_states"]
        ),
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
        event_schedule=_event_schedule(
            event_count=event_count,
            event_interval_ticks=event_interval_ticks,
            factories=factories,
            phase_policy=phase_policy,
        ),
        generation_horizon_end_tick=(
            generation_horizon_end_tick
        ),
        states_per_batch=int(
            protocol["output_states_per_batch"]
        ),
        max_drain_ticks=max_drain_ticks,
    )

    route_counts = Counter(
        cell
        for path in paths.values()
        for cell in set(path)
    )

    return {
        "shared_route_cells_network": sum(
            count > 1
            for count in route_counts.values()
        ),
        "blocked_after_service_ticks": (
            summary.blocked_after_service_ticks
        ),
        "intermediate_queue_full_ticks": (
            summary.intermediate_queue_full_ticks
        ),
        "factory_output_backpressure_ticks": (
            summary.factory_output_backpressure_ticks
        ),
        "suppressed_factory_events": (
            summary.suppressed_factory_events
        ),
        "generated_batch_fraction": (
            summary.generated_batches
            / summary.scheduled_factory_events
        ),
        "max_network_states": (
            summary.max_network_states
        ),
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
        "busiest_cell_utilization_during_generation_horizon": (
            summary.busiest_cell_utilization_during_generation_horizon
        ),
        "all_generated_states_delivered": (
            summary.all_generated_states_delivered
        ),
    }


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    protocol = config["factories"]["protocol"]
    resource = config["resource_model"]
    search = config["m17_layout_search"]

    data_tiles = int(
        resource["data_block"]["tiles"]["value"]
    )
    buffer_cfg = resource["shared_buffer"]

    rows: list[dict[str, object]] = []

    for scenario in search["scenarios"]:
        factories = int(scenario["factory_count"])
        capacity = int(
            scenario["buffer_capacity_states"]
        )
        storage_tiles = replicated_storage_tiles(
            buffer_capacity_states=capacity,
            base_capacity_states=int(
                buffer_cfg["base_capacity_states"]
            ),
            base_storage_tiles=int(
                buffer_cfg["base_storage_tiles"]
            ),
        )

        for sharing_target_raw in search[
            "sharing_targets"
        ]:
            sharing_target = float(
                sharing_target_raw
            )
            candidates = generate_layout_candidates(
                factory_count=factories,
                data_block_tiles=data_tiles,
                shared_buffer_tiles=storage_tiles,
                factory_tiles=int(
                    protocol["distillation_tiles"]
                ),
                sharing_target=sharing_target,
                beam_width=int(search["beam_width"]),
                final_candidates=int(
                    search[
                        "final_candidates_per_target"
                    ]
                ),
                clearance_tiles=int(
                    search["clearance_tiles"]
                ),
                search_margin_tiles=int(
                    search["search_margin_tiles"]
                ),
            )

            for candidate in candidates:
                row = candidate_summary(candidate)
                row.update(
                    {
                        "scenario": scenario["name"],
                        "buffer_capacity_states": capacity,
                        "phase_policy": scenario[
                            "phase_policy"
                        ],
                        "hop_latency_logical_steps": int(
                            scenario[
                                "hop_latency_logical_steps"
                            ]
                        ),
                    }
                )
                row.update(
                    _evaluate_network(
                        candidate=candidate,
                        protocol=protocol,
                        stress=search["stress"],
                        phase_policy=str(
                            scenario["phase_policy"]
                        ),
                        hop_latency_logical_steps=int(
                            scenario[
                                "hop_latency_logical_steps"
                            ]
                        ),
                    )
                )
                rows.append(row)

    objectives = tuple(
        Objective(
            metric=str(spec["metric"]),
            direction=str(spec["direction"]),
        )
        for spec in search["pareto_objectives"]
    )
    frontier, dominated = pareto_partition(
        rows,
        objectives,
    )
    frontier_ids = {
        str(row["candidate_id"])
        + "|"
        + str(row["scenario"])
        for row in frontier
    }
    dominated_by = {
        str(row["candidate_id"])
        + "|"
        + str(row["scenario"]): row[
            "dominated_by"
        ]
        for row in dominated
    }

    enriched: list[dict[str, object]] = []
    for row in rows:
        key = (
            str(row["candidate_id"])
            + "|"
            + str(row["scenario"])
        )
        item = dict(row)
        item["is_pareto"] = (
            key in frontier_ids
        )
        item["dominated_by"] = (
            dominated_by.get(key, [])
        )
        enriched.append(item)

    return {
        "scope": "m17_beam_layout_search",
        "model": search["model"],
        "source": search["source"],
        "candidate_count": len(enriched),
        "pareto_candidate_count": len(frontier),
        "objectives": [
            {
                "metric": objective.metric,
                "direction": objective.direction,
            }
            for objective in objectives
        ],
        "candidates": enriched,
        "pareto_frontier": frontier,
    }


def write_outputs(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    json_path = (
        output_path / "m17_layout_search.json"
    )
    candidates_path = (
        output_path / "m17_candidates.csv"
    )
    pareto_path = (
        output_path / "m17_pareto.csv"
    )

    json_path.write_text(
        json.dumps(
            result,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    candidates = list(result["candidates"])
    pareto = list(result["pareto_frontier"])
    fieldnames = sorted(
        {
            key
            for row in candidates
            for key in row
            if key not in {
                "placements",
                "factory_routes",
                "dominated_by",
            }
        }
    )

    for path, rows in (
        (candidates_path, candidates),
        (pareto_path, pareto),
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
        "candidates_csv": str(candidates_path),
        "pareto_csv": str(pareto_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=(
            "configs/"
            "litinski_m17_beam_layout_search.yaml"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="results/m17_layout_search",
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
                    "candidate_count": result[
                        "candidate_count"
                    ],
                    "pareto_candidate_count": result[
                        "pareto_candidate_count"
                    ],
                },
                "outputs": outputs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
