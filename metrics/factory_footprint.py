from __future__ import annotations

from metrics.resource_accounting import ResourceTerm


class FactoryFootprintError(ValueError):
    """Raised when a factory-footprint parameter is invalid."""


def physical_qubits_per_tile(
    *,
    distance: int,
    physical_qubits_per_d2: float,
) -> int:
    if distance < 1 or distance % 2 == 0:
        raise FactoryFootprintError("distance must be a positive odd integer.")
    if physical_qubits_per_d2 <= 0:
        raise FactoryFootprintError("physical_qubits_per_d2 must be > 0.")

    return int(round(physical_qubits_per_d2 * distance**2))


def factory_distillation_term(
    *,
    factories: int,
    distance: int,
    distillation_tiles_per_factory: int,
    physical_qubits_per_d2: float,
    source: str,
    model: str,
) -> ResourceTerm:
    if factories < 0:
        raise FactoryFootprintError("factories must be >= 0.")
    if distillation_tiles_per_factory < 0:
        raise FactoryFootprintError("distillation_tiles_per_factory must be >= 0.")

    tile_qubits = physical_qubits_per_tile(
        distance=distance,
        physical_qubits_per_d2=physical_qubits_per_d2,
    )
    value = factories * distillation_tiles_per_factory * tile_qubits

    return ResourceTerm(
        name="factory_distillation_qubits",
        value=value,
        source=source,
        model=model,
        confidence="literature_layout_plus_linear_replication_assumption",
        notes=(
            "Factory tile count is literature-backed; replication to many factories "
            "is modeled linearly in v0.1."
        ),
    )
