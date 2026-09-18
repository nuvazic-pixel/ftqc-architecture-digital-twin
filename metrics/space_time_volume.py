from __future__ import annotations


class SpaceTimeVolumeError(ValueError):
    """Raised when STV inputs are invalid."""


def space_time_volume(
    *,
    physical_qubits: int,
    runtime_seconds: float,
) -> float:
    """Return space-time volume in physical-qubit seconds."""
    if physical_qubits < 0:
        raise SpaceTimeVolumeError("physical_qubits must be >= 0.")
    if runtime_seconds < 0:
        raise SpaceTimeVolumeError("runtime_seconds must be >= 0.")

    return physical_qubits * runtime_seconds
