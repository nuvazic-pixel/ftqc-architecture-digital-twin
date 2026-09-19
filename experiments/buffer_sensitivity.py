from __future__ import annotations

import argparse
import json

from metrics.space_time_volume import space_time_volume
from simulator.buffer_consumer import (
    replicated_storage_tiles,
    simulate_buffered_consumer,
)
from simulator.config import load_config
from simulator.system_reliability import (
    logical_failure_budget_from_runtime,
    required_distance_for_runtime_budget,
)


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)

    protocol = config["factories"]["protocol"]
    buffer_cfg = config["buffer_consumer"]
    storage_cfg = config["resource_model"]["buffer_storage"]
    qec = config["qec"]

    target_states = int(config["workload"]["t_count"])
    nominal_runtime = float(
        buffer_cfg["consumer"]["nominal_runtime_seconds"]
    )
    code_cycle_ns = int(config["hardware"]["timing_ns"]["code_cycle"]["value"])
    code_cycle_seconds = code_cycle_ns * 1e-9
    data_tiles = int(config["resource_model"]["data_block"]["tiles"]["value"])
    distillation_tiles = int(protocol["distillation_tiles"])
    tile_factor = float(
        config["resource_model"]["tile_model"]["physical_qubits_per_d2"]["value"]
    )
    max_failure = float(qec["system_failure_budget"]["max_total_failure_probability"])

    rows: list[dict[str, object]] = []

    for capacity in buffer_cfg["sensitivity"]["capacities_states"]:
        capacity = int(capacity)
        storage_tiles = replicated_storage_tiles(
            buffer_capacity_states=capacity,
            base_capacity_states=int(storage_cfg["base_capacity_states"]),
            base_storage_tiles=int(storage_cfg["base_storage_tiles"]),
        )
        total_tiles = data_tiles + distillation_tiles + storage_tiles

        distance = required_distance_for_runtime_budget(
            tile_count=total_tiles,
            runtime_budget_seconds=nominal_runtime,
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

        trace = simulate_buffered_consumer(
            target_states=target_states,
            nominal_runtime_seconds=nominal_runtime,
            batch_duration_ns=batch_duration_ns,
            output_states_per_successful_batch=int(
                protocol["output_states_per_batch"]
            ),
            batch_success_probability=float(
                protocol["batch_success_probability"]
            ),
            buffer_capacity_states=capacity,
            initial_buffer_states=int(buffer_cfg["initial_buffer_states"]),
            seed=int(buffer_cfg["seed"]),
        )

        physical_qubits = int(round(total_tiles * tile_factor * distance**2))
        actual_failure = logical_failure_budget_from_runtime(
            tile_count=total_tiles,
            runtime_seconds=trace.completion_time_seconds,
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
                "completion_time_seconds": trace.completion_time_seconds,
                "quantized_nominal_completion_seconds": (
                    trace.quantized_nominal_completion_seconds
                ),
                "starvation_extension_seconds": (
                    trace.starvation_extension_seconds
                ),
                "raw_deadline_slip_seconds": trace.raw_deadline_slip_seconds,
                "consumer_stall_intervals": trace.consumer_stall_intervals,
                "starved_service_slots": trace.starved_service_slots,
                "overflow_states": trace.overflow_states,
                "mean_buffer_states": trace.mean_buffer_states,
                "max_buffer_states": trace.max_buffer_states,
                "physical_qubits": physical_qubits,
                "post_simulation_failure_budget": actual_failure,
                "post_simulation_reliability_ok": actual_failure <= max_failure,
                "space_time_volume_qubit_seconds": space_time_volume(
                    physical_qubits=physical_qubits,
                    runtime_seconds=trace.completion_time_seconds,
                ),
            }
        )

    return {
        "scope": config["resource_model"]["scope"],
        "model": buffer_cfg["model"],
        "seed": buffer_cfg["seed"],
        "overflow_policy": buffer_cfg["overflow_policy"],
        "storage_scaling_model": storage_cfg["scaling_model"],
        "storage_scaling_source": storage_cfg["source"],
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_buffer_10mT.yaml",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.config), indent=2))


if __name__ == "__main__":
    main()
