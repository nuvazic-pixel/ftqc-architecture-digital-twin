import pytest

from simulator.config import load_config
from simulator.surface_code import (
    SurfaceCodeDomainError,
    logical_error_rate,
    required_code_distance,
    required_code_distance_closed_form,
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


def test_baseline_logical_error_at_d21_matches_target():
    p_logical = logical_error_rate(
        physical_error=1.0e-3,
        physical_error_threshold=1.0e-2,
        fit_A=0.1,
        distance=21,
    )

    assert p_logical == pytest.approx(1.0e-12, rel=1e-12)


def test_baseline_closed_form_distance_is_21():
    d = required_code_distance_closed_form(
        physical_error=1.0e-3,
        physical_error_threshold=1.0e-2,
        fit_A=0.1,
        target_logical_error=1.0e-12,
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
