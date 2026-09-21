from __future__ import annotations

import json
from pathlib import Path

from qad import compare_architectures, recompute_architecture


def main() -> None:
    baseline = recompute_architecture(distance=21, logical_tiles=100)
    candidate = recompute_architecture(distance=23, logical_tiles=100)
    diff = compare_architectures(baseline, candidate)

    output_dir = Path("artifacts/qad")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "baseline.json").write_text(json.dumps(baseline.__dict__, indent=2) + "\n", encoding="utf-8")
    (output_dir / "distance_23.json").write_text(json.dumps(candidate.__dict__, indent=2) + "\n", encoding="utf-8")
    (output_dir / "architecture_diff.json").write_text(json.dumps(diff, indent=2) + "\n", encoding="utf-8")

    print("QAD — Architecture Diff")
    print(f"d: {baseline.distance} -> {candidate.distance}")
    print(f"physical qubits/tile: {baseline.physical_qubits_per_tile} -> {candidate.physical_qubits_per_tile}")
    print(f"delta: {diff['deltas']['physical_qubits_per_tile']['percent']:.2f}%")
    print(f"recomputation: {diff['verification']['recomputation']}")
    print(f"unexplained deltas: {diff['verification']['unexplained_deltas']}")


if __name__ == "__main__":
    main()
