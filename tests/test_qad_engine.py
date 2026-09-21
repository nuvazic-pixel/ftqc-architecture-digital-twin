from qad.engine import compare_architectures, physical_qubits_per_tile, recompute_architecture


def test_d21_tile_accounting() -> None:
    assert physical_qubits_per_tile(21) == 881


def test_d23_tile_accounting() -> None:
    assert physical_qubits_per_tile(23) == 1057


def test_distance_diff_is_fully_explained() -> None:
    a = recompute_architecture(distance=21, logical_tiles=100)
    b = recompute_architecture(distance=23, logical_tiles=100)
    diff = compare_architectures(a, b)

    assert diff["deltas"]["physical_qubits_per_tile"]["absolute"] == 176
    assert round(diff["deltas"]["physical_qubits_per_tile"]["percent"], 2) == 19.98
    assert diff["verification"]["recomputation"] == "MATCH"
    assert diff["verification"]["unexplained_deltas"] == 0


def test_fingerprint_is_deterministic() -> None:
    a = recompute_architecture(distance=21, logical_tiles=100)
    b = recompute_architecture(distance=21, logical_tiles=100)
    assert a.fingerprint == b.fingerprint
