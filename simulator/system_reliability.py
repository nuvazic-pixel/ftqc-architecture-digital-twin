from __future__ import annotations

from typing import Iterable

from simulator.surface_code import logical_error_rate, SurfaceCodeDomainError


class SystemReliabilityError(ValueError):
    """Raised when whole-computation reliability inputs are invalid."""


def expected_total_time_steps(
    *,
    t_count: int,
    factories: int,
    time_steps_per_good_state: float,
) -> float:
    if t_count < 0:
        raise SystemReliabilityError("t_count must be >= 0.")
    if factories <= 0:
        raise SystemReliabilityError("factories must be > 0.")
    if time_steps_per_good_state <= 0:
        raise SystemReliabilityError("time_steps_per_good_state must be > 0.")

    return t_count * time_steps_per_good_state / factories


def logical_failure_budget_estimate(
    *,
    tile_count: int,
    total_time_steps: float,
    distance: int,
    physical_error: float,
    physical_error_threshold: float,
    fit_A: float,
) -> float:
    """
    First-order whole-computation logical-failure budget estimate.

    Following the tile-model resource accounting used in Litinski's worked
    example, this multiplies logical error per tile per code cycle by the number
    of tiles and by d code cycles per logical time step.
    """
    if tile_count <= 0:
        raise SystemReliabilityError("tile_count must be > 0.")
    if total_time_steps < 0:
        raise SystemReliabilityError("total_time_steps must be >= 0.")

    p_logical = logical_error_rate(
        physical_error=physical_error,
        physical_error_threshold=physical_error_threshold,
        fit_A=fit_A,
        distance=distance,
    )
    return tile_count * total_time_steps * distance * p_logical


def required_distance_for_computation(
    *,
    tile_count: int,
    total_time_steps: float,
    physical_error: float,
    physical_error_threshold: float,
    fit_A: float,
    max_total_failure_probability: float,
    allowed_distances: Iterable[int],
) -> int:
    if not 0 < max_total_failure_probability < 1:
        raise SystemReliabilityError(
            "max_total_failure_probability must be in (0, 1)."
        )

    candidates = sorted(set(allowed_distances))
    if not candidates:
        raise SystemReliabilityError("allowed_distances must not be empty.")

    for distance in candidates:
        try:
            estimate = logical_failure_budget_estimate(
                tile_count=tile_count,
                total_time_steps=total_time_steps,
                distance=distance,
                physical_error=physical_error,
                physical_error_threshold=physical_error_threshold,
                fit_A=fit_A,
            )
        except SurfaceCodeDomainError as exc:
            raise SystemReliabilityError(str(exc)) from exc

        if estimate <= max_total_failure_probability:
            return distance

    raise SystemReliabilityError(
        "No allowed code distance satisfies the whole-computation failure budget."
    )


def logical_failure_budget_from_runtime(
    *,
    tile_count: int,
    runtime_seconds: float,
    code_cycle_time_seconds: float,
    distance: int,
    physical_error: float,
    physical_error_threshold: float,
    fit_A: float,
) -> float:
    """
    First-order failure budget expressed directly in wall-clock runtime.

    total code cycles = runtime / code_cycle_time

    This form is useful when consumer stalls or buffering make wall-clock
    runtime differ from the factory-only protocol duration.
    """
    if tile_count <= 0:
        raise SystemReliabilityError("tile_count must be > 0.")
    if runtime_seconds < 0:
        raise SystemReliabilityError("runtime_seconds must be >= 0.")
    if code_cycle_time_seconds <= 0:
        raise SystemReliabilityError("code_cycle_time_seconds must be > 0.")

    p_logical = logical_error_rate(
        physical_error=physical_error,
        physical_error_threshold=physical_error_threshold,
        fit_A=fit_A,
        distance=distance,
    )
    total_code_cycles = runtime_seconds / code_cycle_time_seconds
    return tile_count * total_code_cycles * p_logical


def required_distance_for_runtime_budget(
    *,
    tile_count: int,
    runtime_budget_seconds: float,
    code_cycle_time_seconds: float,
    physical_error: float,
    physical_error_threshold: float,
    fit_A: float,
    max_total_failure_probability: float,
    allowed_distances: Iterable[int],
) -> int:
    """
    Select the smallest distance satisfying a design-time wall-clock budget.

    The stochastic post-simulation runtime should be rechecked afterwards;
    this function intentionally does not select d from one random trajectory.
    """
    if not 0 < max_total_failure_probability < 1:
        raise SystemReliabilityError(
            "max_total_failure_probability must be in (0, 1)."
        )

    candidates = sorted(set(allowed_distances))
    if not candidates:
        raise SystemReliabilityError("allowed_distances must not be empty.")

    for distance in candidates:
        try:
            estimate = logical_failure_budget_from_runtime(
                tile_count=tile_count,
                runtime_seconds=runtime_budget_seconds,
                code_cycle_time_seconds=code_cycle_time_seconds,
                distance=distance,
                physical_error=physical_error,
                physical_error_threshold=physical_error_threshold,
                fit_A=fit_A,
            )
        except SurfaceCodeDomainError as exc:
            raise SystemReliabilityError(str(exc)) from exc

        if estimate <= max_total_failure_probability:
            return distance

    raise SystemReliabilityError(
        "No allowed code distance satisfies the wall-clock failure budget."
    )
