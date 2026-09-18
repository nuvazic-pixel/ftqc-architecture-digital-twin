import pytest

from simulator.config import load_config
from simulator.surface_code import (
    SurfaceCodeDomainError,
    required_code_distance,
)


def test_baseline_required_distance_is_21():
    config = load_config("configs/baseline.yaml")

    d = required_code_distance(
        physical_error=config["hardware"]["errors"]["p_2q"]["value"],
        physical_error_threshold=config["qec"]["physical_error_threshold"]["value"],
        fit_A=config["qec"]["fit_A"]["value"],
        target_logical_error=config["qec"]["target_logical_error"],
        allowed_distances=config["qec"]["allowed_distances"],
    )

    assert d == 21


def test_rejects_at_or_above_threshold():
    with pytest.raises(SurfaceCodeDomainError):
        required_code_distance(
            physical_error=0.01,
            physical_error_threshold=0.01,
            fit_A=0.1,
            target_logical_error=1e-12,
            allowed_distances=[13, 15, 17, 19, 21, 23],
        )
