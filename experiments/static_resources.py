from __future__ import annotations

import argparse
import json

from simulator.config import load_config
from simulator.factory import effective_factory_rate, minimum_factories
from simulator.surface_code import required_code_distance
from metrics.physical_qubits import data_block_physical_qubits
from metrics.runtime import runtime_from_t_state_supply
from metrics.space_time_volume import space_time_volume


def run(config_path: str) -> dict[str, float | int | str]:
    config = load_config(config_path)

    d = required_code_distance(
        physical_error=config["hardware"]["errors"]["p_2q"]["value"],
        physical_error_threshold=config["qec"]["physical_error_threshold"]["value"],
        fit_A=config["qec"]["fit_A"]["value"],
        target_logical_error=config["qec"]["target_logical_error"],
        allowed_distances=config["qec"]["allowed_distances"],
    )

    max_runtime = config["optimizer"]["constraints"]["max_runtime_seconds"]
    zeta = config["hardware"]["topology"]["zeta"]

    n_factories = minimum_factories(
        distance=d,
        t_count=config["workload"]["t_count"],
        wall_time_seconds=max_runtime,
        routing_factor=zeta,
        config=config,
    )

    effective_rate = effective_factory_rate(
        distance=d,
        routing_factor=zeta,
        config=config,
    )

    runtime_seconds = runtime_from_t_state_supply(
        t_count=config["workload"]["t_count"],
        factories=n_factories,
        effective_states_per_second_per_factory=effective_rate,
    )

    physical_qubits = data_block_physical_qubits(
        logical_qubits=config["workload"]["logical_qubits"],
        distance=d,
        physical_qubits_per_d2=config["resource_model"]["data_block"][
            "physical_qubits_per_d2"
        ]["value"],
    )

    stv = space_time_volume(
        physical_qubits=physical_qubits,
        runtime_seconds=runtime_seconds,
    )

    return {
        "scope": config["resource_model"]["scope"],
        "code_distance": d,
        "factories": n_factories,
        "physical_qubits": physical_qubits,
        "runtime_seconds": runtime_seconds,
        "space_time_volume_qubit_seconds": stv,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/baseline.yaml")
    args = parser.parse_args()

    print(json.dumps(run(args.config), indent=2))


if __name__ == "__main__":
    main()
