from __future__ import annotations


class ResourceMetricError(ValueError):
    """Raised when resource-metric inputs are invalid."""


def data_block_physical_qubits(
    *,
    logical_qubits: int,
    distance: int,
    physical_qubits_per_d2: float,
) -> int:
    """
    Estimate the physical-qubit footprint of the logical data block.

    v0.1 model:
        N_phys,data = ceil(N_logical * c_patch * d^2)

    This intentionally excludes magic-state factories, routing ancillas,
    buffers, control hardware, and other architecture overheads. The result is
    therefore a lower-bound scope, not a total-machine qubit count.
    """
    if logical_qubits < 0:
        raise ResourceMetricError("logical_qubits must be >= 0.")
    if distance < 1 or distance % 2 == 0:
        raise ResourceMetricError("distance must be a positive odd integer.")
    if physical_qubits_per_d2 <= 0:
        raise ResourceMetricError("physical_qubits_per_d2 must be > 0.")

    value = logical_qubits * physical_qubits_per_d2 * (distance**2)
    return int(round(value))
