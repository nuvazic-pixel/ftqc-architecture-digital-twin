from __future__ import annotations

import argparse
import json

import numpy as np

from experiments.litinski_minimal_setup import run as run_protocol_consistent
from metrics.space_time_volume import space_time_volume
from simulator.config import load_config
from simulator.stochastic_factory import (
    protocol_batch_duration_seconds,
    simulate_single_factory_completion_times,
    single_factory_completion_time_moments,
    summarize_completion_times,
)


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)
    protocol = config["factories"]["protocol"]
    stochastic = config["factories"]["stochastic"]

    factories = int(config["factories"]["count"])
    if factories != 1:
        raise ValueError(
            "Milestone 6 stochastic completion-time model supports exactly one "
            "factory. Multi-factory synchronization is a separate milestone."
        )

    deterministic = run_protocol_consistent(config_path)
    distance = int(deterministic["code_distance"])
    cycle_seconds = config["hardware"]["timing_ns"]["code_cycle"]["value"] * 1e-9

    batch_duration = protocol_batch_duration_seconds(
        distance=distance,
        protocol_steps_per_batch=protocol["protocol_steps_per_batch"],
        code_cycle_time_seconds=cycle_seconds,
    )
    moments = single_factory_completion_time_moments(
        t_count=config["workload"]["t_count"],
        output_states_per_batch=protocol["output_states_per_batch"],
        batch_success_probability=protocol["batch_success_probability"],
        batch_duration_seconds=batch_duration,
    )
    samples = simulate_single_factory_completion_times(
        t_count=config["workload"]["t_count"],
        output_states_per_batch=protocol["output_states_per_batch"],
        batch_success_probability=protocol["batch_success_probability"],
        batch_duration_seconds=batch_duration,
        runs=stochastic["runs"],
        seed=stochastic["seed"],
    )
    runtime_summary = summarize_completion_times(
        samples,
        deadline_seconds=stochastic["deadline_seconds"],
    )

    physical_qubits = int(deterministic["physical_qubits"])
    stv_samples = samples * physical_qubits
    stv_summary = {
        "mean_qubit_seconds": float(np.mean(stv_samples)),
        "p50_qubit_seconds": float(np.quantile(stv_samples, 0.50)),
        "p95_qubit_seconds": float(np.quantile(stv_samples, 0.95)),
        "p99_qubit_seconds": float(np.quantile(stv_samples, 0.99)),
    }

    continuous_runtime = float(deterministic["runtime_seconds"])
    discrete_expected_runtime = moments.mean_runtime_seconds

    return {
        "scope": stochastic["scope"],
        "protocol": protocol["name"],
        "code_distance": distance,
        "factories": factories,
        "successful_batches_required": moments.successful_batches_required,
        "batch_duration_seconds": batch_duration,
        "analytical_mean_attempted_batches": moments.mean_attempted_batches,
        "analytical_mean_runtime_seconds": discrete_expected_runtime,
        "analytical_std_runtime_seconds": moments.std_runtime_seconds,
        "continuous_expected_rate_runtime_seconds": continuous_runtime,
        "final_batch_quantization_overhead_seconds": (
            discrete_expected_runtime - continuous_runtime
        ),
        "monte_carlo": runtime_summary,
        "physical_qubits": physical_qubits,
        "stochastic_stv": stv_summary,
        "deterministic_stv_qubit_seconds": space_time_volume(
            physical_qubits=physical_qubits,
            runtime_seconds=continuous_runtime,
        ),
        "deadline_seconds": stochastic["deadline_seconds"],
        "model": stochastic["model"],
        "multi_factory_supported": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_stochastic_10mT.yaml",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.config), indent=2))


if __name__ == "__main__":
    main()
