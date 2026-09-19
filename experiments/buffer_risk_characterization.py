from __future__ import annotations

import argparse
import json

from simulator.buffer_consumer import replicated_storage_tiles
from simulator.buffer_risk import analyze_buffer_risk
from simulator.config import load_config
from simulator.system_reliability import (
    logical_failure_budget_from_runtime,
    required_distance_for_runtime_budget,
)


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)

    risk_cfg = config["buffer_risk"]
    protocol = config["factories"]["protocol"]
    qec = config["qec"]

    target_states = int(config["workload"]["t_count"])
    nominal_runtime_seconds = float(
        risk_cfg["consumer"]["nominal_runtime_seconds"]
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
    max_failure = float(qec["system_failure_budget"]["max_total_failure_probability"])

    rows: list[dict[str, object]] = []

    for capacity in risk_cfg["sensitivity"]["capacities_states"]:
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

        batch_duration_ns = (
            distance
            * int(protocol["protocol_steps_per_batch"])
            * code_cycle_ns
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
            initial_buffer_states=int(risk_cfg["initial_buffer_states"]),
        )

        physical_qubits = int(round(total_tiles * tile_factor * distance**2))
        design_failure = logical_failure_budget_from_runtime(
            tile_count=total_tiles,
            runtime_seconds=nominal_runtime_seconds,
            code_cycle_time_seconds=code_cycle_seconds,
            distance=distance,
            physical_error=config["hardware"]["errors"]["p_2q"]["value"],
            physical_error_threshold=qec["physical_error_threshold"]["value"],
            fit_A=qec["fit_A"]["value"],
        )

        rows.append(
            {
                "buffer_capacity_states": capacity,
                "storage_tiles": storage_tiles,
                "total_tiles": total_tiles,
                "code_distance": distance,
                "batch_duration_seconds": batch_duration_ns / 1e9,
                "physical_qubits": physical_qubits,
                "design_failure_budget": design_failure,
                "probability_any_starvation": risk.probability_any_starvation,
                "probability_no_starvation": risk.probability_no_starvation,
                "log10_probability_no_starvation": (
                    risk.log10_probability_no_starvation
                ),
                "expected_starved_service_slots": (
                    risk.expected_starved_service_slots
                ),
                "expected_stall_intervals": risk.expected_stall_intervals,
                "expected_overflow_states": risk.expected_overflow_states,
                "mean_buffer_states_after_service": (
                    risk.mean_buffer_states_after_service
                ),
                "service_period_batches": risk.service_period_batches,
                "batches_in_nominal_horizon": risk.batches_in_horizon,
                "final_service_slots": risk.final_service_slots,
                "quantized_nominal_completion_seconds": (
                    risk.quantized_nominal_completion_seconds
                ),
            }
        )

    return {
        "scope": config["resource_model"]["scope"],
        "model": risk_cfg["model"],
        "primary_metric": risk_cfg["primary_metric"]["name"],
        "sampling_error": "none_within_model",
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_buffer_risk_10mT.yaml",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.config), indent=2))


if __name__ == "__main__":
    main()
