from __future__ import annotations

import math
from typing import Iterable


class SurfaceCodeDomainError(ValueError):
    """Raised when parameters are outside the model's valid physical regime."""


def logical_error_rate(
    *,
    physical_error: float,
    physical_error_threshold: float,
    fit_A: float,
    distance: int,
) -> float:
    """Estimate logical error using the configured surface-code scaling fit."""
    if physical_error <= 0:
        raise SurfaceCodeDomainError("physical_error must be > 0.")
    if physical_error_threshold <= 0:
        raise SurfaceCodeDomainError("physical_error_threshold must be > 0.")
    if physical_error >= physical_error_threshold:
        raise SurfaceCodeDomainError(
            "Physical error is at or above the configured QEC threshold; "
            "sub-threshold scaling is invalid."
        )
    if fit_A <= 0:
        raise SurfaceCodeDomainError("fit_A must be > 0.")
    if distance < 1 or distance % 2 == 0:
        raise SurfaceCodeDomainError("Surface-code distance must be a positive odd integer.")

    return fit_A * (physical_error / physical_error_threshold) ** ((distance + 1) / 2)


def required_code_distance(
    *,
    physical_error: float,
    physical_error_threshold: float,
    fit_A: float,
    target_logical_error: float,
    allowed_distances: Iterable[int],
) -> int:
    """
    Return the smallest allowed odd distance meeting the logical-error target.

    A tiny floating-point tolerance is used at the target boundary so exact
    analytical cases (for example d=21 in the baseline) are not incorrectly
    promoted to the next distance by binary rounding.
    """
    if target_logical_error <= 0:
        raise SurfaceCodeDomainError("target_logical_error must be > 0.")

    candidates = sorted(set(allowed_distances))
    if not candidates:
        raise SurfaceCodeDomainError("allowed_distances must not be empty.")

    for distance in candidates:
        p_logical = logical_error_rate(
            physical_error=physical_error,
            physical_error_threshold=physical_error_threshold,
            fit_A=fit_A,
            distance=distance,
        )
        if p_logical <= target_logical_error or math.isclose(
            p_logical,
            target_logical_error,
            rel_tol=1e-12,
            abs_tol=0.0,
        ):
            return distance

    raise SurfaceCodeDomainError(
        "No allowed code distance satisfies the configured logical-error target."
    )


def required_code_distance_closed_form(
    *,
    physical_error: float,
    physical_error_threshold: float,
    fit_A: float,
    target_logical_error: float,
) -> int:
    """
    Closed-form reference calculation; returns the next valid odd distance.

    The exponent is snapped to the nearest integer when it is numerically
    indistinguishable from that integer, avoiding ceil() boundary drift.
    """
    if physical_error >= physical_error_threshold:
        raise SurfaceCodeDomainError(
            "Physical error is at or above the configured QEC threshold; "
            "sub-threshold scaling is invalid."
        )
    exponent = math.log(target_logical_error / fit_A) / math.log(
        physical_error / physical_error_threshold
    )

    nearest_integer = round(exponent)
    if math.isclose(exponent, nearest_integer, rel_tol=1e-12, abs_tol=1e-12):
        exponent = float(nearest_integer)

    return 2 * math.ceil(exponent) - 1
