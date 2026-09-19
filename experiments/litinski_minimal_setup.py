from __future__ import annotations

import argparse
import json

from metrics.space_time_volume import space_time_volume
from simulator.config import load_config
from simulator.protocol_factory import (
    expected_time_steps_per_good_state,
    minimum_protocol_factories,
    protocol_factory_throughput,
    protocol_runtime_seconds,
)
from simulator.system_reliability import (
    expected_total_time_steps,
    logical_failure_budget_estimate,
    required_distance_for_computation,
)


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)

    protocol = config["factories"]["protocol"]
    factories = int(config["factories"]["count"])
    t_count = int(config["workload"]["t_count"])

    steps_per_state = expected_time_steps_per_good_state(
        output_states_per_batch=protocol["output_states_per_batch"],
        protocol_steps_per_batch=protocol["protocol_steps_per_batch"],
        batch_success_probability=protocol["batch_success_probability"],
    )
    total_time_steps = expected_total_time_steps(
        t_count=t_count,
        factories=factories,
        time_steps_per_good_state=steps_per_state,
    )

    data_tiles = int(config["resource_model"]["data_block"]["tiles"]["value"])
    factory_tiles = int(protocol["distillation_tiles"])
    storage_tiles = int(protocol["output_storage_tiles"])
    total_tiles = data_tiles + factories * (factory_tiles + storage_tiles)

    d = required_distance_for_computation(
        tile_count=total_tiles,
        total_time_steps=total_time_steps,
        physical_error=config["hardware"]["errors"]["p_2q"]["value"],
        physical_error_threshold=config["qec"]["physical_error_threshold"]["value"],
        fit_A=config["qec"]["fit_A"]["value"],
        max_total_failure_probability=config["qec"]["system_failure_budget"][
            "max_total_failure_probability"
        ],
        allowed_distances=config["qec"]["allowed_distances"],
    )

    cycle_seconds = config["hardware"]["timing_ns"]["code_cycle"]["value"] * 1e-9
    throughput = protocol_factory_throughput(
        distance=d,
        code_cycle_time_seconds=cycle_seconds,
        output_states_per_batch=protocol["output_states_per_batch"],
        protocol_steps_per_batch=protocol["protocol_steps_per_batch"],
        batch_success_probability=protocol["batch_success_probability"],
    )
    runtime_seconds = protocol_runtime_seconds(
        t_count=t_count,
        factories=factories,
        states_per_second_per_factory=throughput,
    )

    min_factories_for_runtime = minimum_protocol_factories(
        t_count=t_count,
        max_runtime_seconds=config["optimizer"]["constraints"]["max_runtime_seconds"],
        states_per_second_per_factory=throughput,
    )

    tile_factor = config["resource_model"]["tile_model"]["physical_qubits_per_d2"][
        "value"
    ]
    physical_qubits = int(round(total_tiles * tile_factor * d**2))

    failure_estimate = logical_failure_budget_estimate(
        tile_count=total_tiles,
        total_time_steps=total_time_steps,
        distance=d,
        physical_error=config["hardware"]["errors"]["p_2q"]["value"],
        physical_error_threshold=config["qec"]["physical_error_threshold"]["value"],
        fit_A=config["qec"]["fit_A"]["value"],
    )

    stv = space_time_volume(
        physical_qubits=physical_qubits,
        runtime_seconds=runtime_seconds,
    )

    return {
        "scope": config["resource_model"]["scope"],
        "protocol": protocol["name"],
        "factories": factories,
        "minimum_factories_for_runtime_at_selected_d": min_factories_for_runtime,
        "time_steps_per_good_state": steps_per_state,
        "total_time_steps": total_time_steps,
        "code_distance": d,
        "estimated_total_logical_failure": failure_estimate,
        "states_per_second_per_factory": throughput,
        "runtime_seconds": runtime_seconds,
        "data_block_tiles": data_tiles,
        "factory_tiles": factory_tiles,
        "storage_tiles": storage_tiles,
        "total_tiles": total_tiles,
        "physical_qubits": physical_qubits,
        "space_time_volume_qubit_seconds": stv,
        "throughput_binding_status": "protocol_derived",
        "routing_workspace_status": "embedded_in_named_layout",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_minimal_10mT.yaml",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.config), indent=2))


if __name__ == "__main__":
    main()
