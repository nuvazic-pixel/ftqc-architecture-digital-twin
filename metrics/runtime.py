from __future__ import annotations


class RuntimeMetricError(ValueError):
    """Raised when runtime-model inputs are invalid."""


def runtime_from_t_state_supply(
    *,
    t_count: int,
    factories: int,
    effective_states_per_second_per_factory: float,
) -> float:
    """
    Compute the T-state supply-limited runtime.

    T_wall = T_count / (N_factories * r_T,eff)

    This v0.1 runtime is intentionally supply-limited and does not yet include
    Clifford depth, measurement latency, routing stalls, or burstiness.
    """
    if t_count < 0:
        raise RuntimeMetricError("t_count must be >= 0.")
    if factories < 0:
        raise RuntimeMetricError("factories must be >= 0.")
    if effective_states_per_second_per_factory <= 0:
        raise RuntimeMetricError(
            "effective_states_per_second_per_factory must be > 0."
        )

    if t_count == 0:
        return 0.0
    if factories == 0:
        raise RuntimeMetricError("factories must be > 0 when t_count > 0.")

    return t_count / (factories * effective_states_per_second_per_factory)
