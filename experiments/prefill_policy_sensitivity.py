from __future__ import annotations

import argparse
import json

from simulator.buffer_consumer import replicated_storage_tiles
from simulator.buffer_risk import analyze_buffer_risk
from simulator.config import load_config
from simulator.prefill_policy import prefill_cost, requested_initial_states
from simulator.system_reliability import (
    logical_failure_budget_from_runtime,
    required_distance_for_runtime_budget,
)


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)

    policy = config["prefill_policy"]
    protocol = config["factories"]["protocol"]
    qec = config["qec"]

    target_states = int(config["workload"]["t_count"])
    nominal_runtime_seconds = float(
        policy["consumer"]["nominal_runtime_seconds"]
    )
    nominal_runtime_ns = int(round(nominal_runtime_seconds * 1_000_000_000))

    code_cycle_ns = int(config["hardware"]["timing_ns"]["code_cycle"]["value"])
    code_cycle_seconds = code_cycle_ns * 1e-9

    data_tiles = int(config["resource_model"]["data_block"]["tiles"]["value"])
    distillation_tiles = int(protocol["distillation_tiles"])
    storage_cfg = config["resource_model"]["buffer_storage"]
    tile_factor = float(
        config["resource_model"]["tile_model"]["physical_qubits_per_d2"]["value"]
    )
    max_failure = float(
        qec["system_failure_budget"]["max_total_failure_probability"]
    )

    rows: list[dict[str, object]] = []

    for capacity in policy["sensitivity"]["capacities_states"]:
        capacity = int(capacity)

        storage_tiles = replicated_storage_tiles(
            buffer_capacity_states=capacity,
            base_capacity_states=int(storage_cfg["base_capacity_states"]),
            base_storage_tiles=int(storage_cfg["base_storage_tiles"]),
        )
        total_tiles = data_tiles + distillation_tiles + storage_tiles

        distance = required_distance_for_runtime_budget(
            tile_count=total_tiles,
            runtime_budget_seconds=nominal_runtime_seconds,
            code_cycle_time_seconds=code_cycle_seconds,
            physical_error=config["hardware"]["errors"]["p_2q"]["value"],
            physical_error_threshold=qec["physical_error_threshold"]["value"],
            fit_A=qec["fit_A"]["value"],
            max_total_failure_probability=max_failure,
            allowed_distances=qec["allowed_distances"],
        )

        batch_duration_seconds = (
            distance
            * int(protocol["protocol_steps_per_batch"])
            * code_cycle_seconds
        )
        batch_duration_ns = int(round(batch_duration_seconds * 1_000_000_000))

        physical_qubits = int(round(total_tiles * tile_factor * distance**2))
        execution_failure_budget = logical_failure_budget_from_runtime(
            tile_count=total_tiles,
            runtime_seconds=nominal_runtime_seconds,
            code_cycle_time_seconds=code_cycle_seconds,
            distance=distance,
            physical_error=config["hardware"]["errors"]["p_2q"]["value"],
            physical_error_threshold=qec["physical_error_threshold"]["value"],
            fit_A=qec["fit_A"]["value"],
        )

        for fill_fraction in policy["sensitivity"]["fill_fractions"]:
            fill_fraction = float(fill_fraction)
            initial_states = requested_initial_states(
                buffer_capacity_states=capacity,
                fill_fraction=fill_fraction,
            )
            cost = prefill_cost(
                requested_states=initial_states,
                output_states_per_successful_batch=int(
                    protocol["output_states_per_batch"]
                ),
                batch_success_probability=float(
                    protocol["batch_success_probability"]
                ),
                batch_duration_seconds=batch_duration_seconds,
            )

            risk = analyze_buffer_risk(
                target_states=target_states,
                nominal_runtime_ns=nominal_runtime_ns,
                batch_duration_ns=batch_duration_ns,
                output_states_per_successful_batch=int(
                    protocol["output_states_per_batch"]
                ),
                batch_success_probability=float(
                    protocol["batch_success_probability"]
                ),
                capacity_states=capacity,
                initial_buffer_states=initial_states,
            )

            prefill_failure_increment = logical_failure_budget_from_runtime(
                tile_count=total_tiles,
                runtime_seconds=cost.expected_prefill_seconds,
                code_cycle_time_seconds=code_cycle_seconds,
                distance=distance,
                physical_error=config["hardware"]["errors"]["p_2q"]["value"],
                physical_error_threshold=qec["physical_error_threshold"]["value"],
                fit_A=qec["fit_A"]["value"],
            )

            rows.append(
                {
                    "buffer_capacity_states": capacity,
                    "fill_fraction": fill_fraction,
                    "initial_buffer_states": initial_states,
                    "code_distance": distance,
                    "physical_qubits": physical_qubits,
                    "successful_prefill_batches_required": (
                        cost.successful_batches_required
                    ),
                    "expected_prefill_seconds": cost.expected_prefill_seconds,
                    "std_prefill_seconds": cost.std_prefill_seconds,
                    "discarded_prefill_states": (
                        cost.discarded_states_from_final_prefill_batch
                    ),
                    "probability_any_starvation": (
                        risk.probability_any_starvation
                    ),
                    "probability_no_starvation": (
                        risk.probability_no_starvation
                    ),
                    "log10_probability_no_starvation": (
                        risk.log10_probability_no_starvation
                    ),
                    "expected_starved_service_slots": (
                        risk.expected_starved_service_slots
                    ),
                    "execution_failure_budget": execution_failure_budget,
                    "expected_prefill_failure_increment": (
                        prefill_failure_increment
                    ),
                    "conservative_expected_campaign_failure_budget": (
                        execution_failure_budget + prefill_failure_increment
                    ),
                }
            )

    return {
        "scope": config["resource_model"]["scope"],
        "model": policy["model"],
        "prefill_failure_budget_model": (
            policy["prefill_failure_budget_model"]
        ),
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_prefill_policy_10mT.yaml",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.config), indent=2))


if __name__ == "__main__":
    main()
