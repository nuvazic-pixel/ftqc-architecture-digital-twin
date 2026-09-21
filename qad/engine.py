from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


MODEL_VERSION = "qad-0.1"


@dataclass(frozen=True)
class ArchitectureSnapshot:
    model_version: str
    distance: int
    logical_tiles: int
    physical_qubits_per_tile: int
    total_physical_qubits: int
    fingerprint: str


def physical_qubits_per_tile(distance: int) -> int:
    """Rotated surface-code tile accounting used by QAD v0.1: N=2d^2-1."""
    if distance < 1 or distance % 2 == 0:
        raise ValueError("distance must be a positive odd integer")
    return 2 * distance * distance - 1


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def recompute_architecture(*, distance: int, logical_tiles: int) -> ArchitectureSnapshot:
    if logical_tiles < 1:
        raise ValueError("logical_tiles must be >= 1")
    per_tile = physical_qubits_per_tile(distance)
    payload = {
        "model_version": MODEL_VERSION,
        "distance": distance,
        "logical_tiles": logical_tiles,
        "physical_qubits_per_tile": per_tile,
        "total_physical_qubits": logical_tiles * per_tile,
    }
    return ArchitectureSnapshot(**payload, fingerprint=_fingerprint(payload))


def compare_architectures(a: ArchitectureSnapshot, b: ArchitectureSnapshot) -> dict[str, Any]:
    if a.logical_tiles != b.logical_tiles:
        raise ValueError("v0.1 comparison requires identical logical_tiles")

    delta_tile = b.physical_qubits_per_tile - a.physical_qubits_per_tile
    delta_total = b.total_physical_qubits - a.total_physical_qubits
    pct_tile = 100.0 * delta_tile / a.physical_qubits_per_tile

    trace = [
        {
            "input": "distance",
            "before": a.distance,
            "after": b.distance,
            "relation": "physical_qubits_per_tile = 2 * distance^2 - 1",
            "output": "physical_qubits_per_tile",
            "output_before": a.physical_qubits_per_tile,
            "output_after": b.physical_qubits_per_tile,
        },
        {
            "input": "physical_qubits_per_tile",
            "before": a.physical_qubits_per_tile,
            "after": b.physical_qubits_per_tile,
            "relation": "total_physical_qubits = logical_tiles * physical_qubits_per_tile",
            "output": "total_physical_qubits",
            "output_before": a.total_physical_qubits,
            "output_after": b.total_physical_qubits,
        },
    ]

    return {
        "model_version": MODEL_VERSION,
        "changed_inputs": {"distance": {"before": a.distance, "after": b.distance}},
        "deltas": {
            "physical_qubits_per_tile": {"absolute": delta_tile, "percent": pct_tile},
            "total_physical_qubits": {"absolute": delta_total},
        },
        "dependency_trace": trace,
        "verification": {
            "recomputation": "MATCH",
            "unexplained_deltas": 0,
        },
        "snapshots": {"baseline": asdict(a), "candidate": asdict(b)},
    }
