from __future__ import annotations

import argparse
import json

from metrics.buffer_workspace import (
    factory_output_buffer_term,
    unmodeled_workspace_term,
)
from metrics.factory_footprint import factory_distillation_term
from metrics.resource_accounting import ResourceTerm
from metrics.routing_overhead import unmodeled_routing_term
from metrics.space_time_volume import space_time_volume
from metrics.total_physical_qubits import total_physical_qubits
from simulator.config import load_config
from simulator.factory import effective_factory_rate, minimum_factories
from simulator.surface_code import required_code_distance
from metrics.physical_qubits import data_block_physical_qubits
from metrics.runtime import runtime_from_t_state_supply


def run(config_path: str) -> dict[str, object]:
    config = load_config(config_path)

    d = required_code_distance(
        physical_error=config["hardware"]["errors"]["p_2q"]["value"],
        physical_error_threshold=config["qec"]["physical_error_threshold"]["value"],
        fit_A=config["qec"]["fit_A"]["value"],
        target_logical_error=config["qec"]["target_logical_error"],
        allowed_distances=config["qec"]["allowed_distances"],
    )

    zeta = config["hardware"]["topology"]["zeta"]
    max_runtime = config["optimizer"]["constraints"]["max_runtime_seconds"]
    factories = minimum_factories(
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
        factories=factories,
        effective_states_per_second_per_factory=effective_rate,
    )

    data_value = data_block_physical_qubits(
        logical_qubits=config["workload"]["logical_qubits"],
        distance=d,
        physical_qubits_per_d2=config["resource_model"]["data_block"][
            "physical_qubits_per_d2"
        ]["value"],
    )
    data_term = ResourceTerm(
        name="data_block_qubits",
        value=data_value,
        source=config["resource_model"]["data_block"]["physical_qubits_per_d2"][
            "source"
        ],
        model=config["resource_model"]["data_block"]["scope"],
        confidence="lower_bound",
    )

    protocol = config["resource_model"]["factory"]["protocol"]
    tile_factor = config["resource_model"]["tile_model"]["physical_qubits_per_d2"]

    factory_term = factory_distillation_term(
        factories=factories,
        distance=d,
        distillation_tiles_per_factory=protocol["distillation_tiles"],
        physical_qubits_per_d2=tile_factor["value"],
        source=protocol["source"],
        model=protocol["name"],
    )
    buffer_term = factory_output_buffer_term(
        factories=factories,
        distance=d,
        storage_tiles_per_factory=protocol["output_storage_tiles"],
        physical_qubits_per_d2=tile_factor["value"],
        source=protocol["source"],
        model=protocol["name"],
    )

    accounting = total_physical_qubits(
        data_block=data_term,
        factory_distillation=factory_term,
        factory_output_buffer=buffer_term,
        routing=unmodeled_routing_term(),
        workspace=unmodeled_workspace_term(),
    )

    known_subtotal_stv = space_time_volume(
        physical_qubits=accounting.known_subtotal,
        runtime_seconds=runtime_seconds,
    )

    return {
        "scope": config["resource_model"]["scope"],
        "code_distance": d,
        "factories": factories,
        "runtime_seconds": runtime_seconds,
        "throughput_binding_status": config["resource_model"]["factory"][
            "throughput_binding"
        ]["status"],
        "known_subtotal_physical_qubits": accounting.known_subtotal,
        "total_physical_qubits": accounting.total_physical_qubits,
        "accounting_complete": accounting.complete,
        "missing_terms": list(accounting.missing_terms),
        "known_subtotal_stv_qubit_seconds": known_subtotal_stv,
        "terms": [
            {
                "name": term.name,
                "value": term.value,
                "source": term.source,
                "model": term.model,
                "confidence": term.confidence,
                "notes": term.notes,
            }
            for term in accounting.terms
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/baseline.yaml")
    args = parser.parse_args()
    print(json.dumps(run(args.config), indent=2))


if __name__ == "__main__":
    main()
