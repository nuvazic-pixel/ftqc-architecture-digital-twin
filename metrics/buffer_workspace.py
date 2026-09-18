from __future__ import annotations

from metrics.factory_footprint import physical_qubits_per_tile
from metrics.resource_accounting import ResourceTerm


class BufferWorkspaceError(ValueError):
    """Raised when buffer/workspace parameters are invalid."""


def factory_output_buffer_term(
    *,
    factories: int,
    distance: int,
    storage_tiles_per_factory: int,
    physical_qubits_per_d2: float,
    source: str,
    model: str,
) -> ResourceTerm:
    if factories < 0:
        raise BufferWorkspaceError("factories must be >= 0.")
    if storage_tiles_per_factory < 0:
        raise BufferWorkspaceError("storage_tiles_per_factory must be >= 0.")

    tile_qubits = physical_qubits_per_tile(
        distance=distance,
        physical_qubits_per_d2=physical_qubits_per_d2,
    )
    value = factories * storage_tiles_per_factory * tile_qubits

    return ResourceTerm(
        name="factory_output_buffer_qubits",
        value=value,
        source=source,
        model=model,
        confidence="literature_layout_plus_linear_replication_assumption",
        notes=(
            "Storage-tile count is taken from the named minimal layout; sharing "
            "buffers across many factories is not yet modeled."
        ),
    )


def unmodeled_workspace_term() -> ResourceTerm:
    return ResourceTerm(
        name="workspace_qubits",
        value=None,
        source="unmodeled",
        model="unmodeled",
        confidence="unknown",
        notes="Lattice-surgery workspace is a required term and is not yet modeled.",
    )
