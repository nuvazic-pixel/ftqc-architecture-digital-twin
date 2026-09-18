from __future__ import annotations

import math
from typing import Any


class FactoryModelError(ValueError):
    """Raised when factory parameters are missing or physically invalid."""


def factory_rate(*, distance: int, config: dict[str, Any]) -> float:
    """
    Return the configured raw magic-state throughput for an exact code distance.

    v0.1 intentionally avoids interpolation. Exact configured points are used so
    regression fixtures remain transparent and reproducible.
    """
    entries = config["factories"]["throughput_data"]

    for entry in entries:
        if entry["d"] == distance:
            rate = float(entry["states_per_second"])
            if rate <= 0:
                raise FactoryModelError("Factory throughput must be > 0.")
            return rate

    raise FactoryModelError(
        f"No factory throughput datum is configured for code distance d={distance}."
    )


def effective_factory_rate(
    *,
    distance: int,
    routing_factor: float,
    config: dict[str, Any],
) -> float:
    """
    Apply the v0.1 scalar routing penalty to raw factory throughput.
    """
    if routing_factor <= 0:
        raise FactoryModelError("routing_factor must be > 0.")

    return factory_rate(distance=distance, config=config) / routing_factor


def minimum_factories(
    *,
    distance: int,
    t_count: int,
    wall_time_seconds: float,
    routing_factor: float,
    config: dict[str, Any],
) -> int:
    """
    Minimum number of factories required to satisfy total T-state demand.

    N_fac = ceil((T_count / T_wall) / r_T_eff)
    """
    if t_count < 0:
        raise FactoryModelError("t_count must be >= 0.")
    if wall_time_seconds <= 0:
        raise FactoryModelError("wall_time_seconds must be > 0.")

    if t_count == 0:
        return 0

    demand_rate = t_count / wall_time_seconds
    rate = effective_factory_rate(
        distance=distance,
        routing_factor=routing_factor,
        config=config,
    )
    return math.ceil(demand_rate / rate)
