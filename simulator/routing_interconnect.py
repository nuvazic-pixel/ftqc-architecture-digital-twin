from __future__ import annotations

from dataclasses import dataclass
import math


class RoutingInterconnectError(ValueError):
    """Raised when routing/interconnect geometry inputs are invalid."""


@dataclass(frozen=True)
class RoutingInterconnectFootprint:
    model: str
    source: str
    factory_count: int
    baseline_factory_count: int
    factory_tile_area: int
    effective_factory_span_tiles: int
    clearance_tiles: int
    lane_width_tiles: int
    branch_spur_tiles: int
    extra_factory_count: int
    slot_pitch_tiles: int
    trunk_tiles: int
    spur_tiles: int
    total_routing_tiles: int


def square_envelope_factory_span(*, factory_tile_area: int) -> int:
    """
    Deterministic compact-envelope proxy for factory linear span.

    This does not claim the cited 44-tile factory is literally square. It uses
    ceil(sqrt(area)) as a reproducible first-order placement scale when an exact
    routed factory polygon is not yet encoded.
    """
    if factory_tile_area <= 0:
        raise RoutingInterconnectError("factory_tile_area must be > 0.")
    return math.ceil(math.sqrt(factory_tile_area))


def manhattan_trunk_and_spur_footprint(
    *,
    factory_count: int,
    factory_tile_area: int,
    baseline_factory_count: int = 1,
    clearance_tiles: int = 1,
    lane_width_tiles: int = 1,
    branch_spur_tiles: int = 1,
    source: str = "model_assumption",
) -> RoutingInterconnectFootprint:
    """
    First layout-aware routing lower-bound for a shared-buffer architecture.

    The one-factory Litinski-style minimal layout is treated as the embedded
    baseline: its factory-to-storage connection is already represented by the
    named layout and receives zero *additional* routing tiles.

    Each additional factory extends a one-lane Manhattan trunk by one placement
    pitch and adds one branch spur to the trunk:

        effective span = ceil(sqrt(factory_tile_area))
        slot pitch     = effective span + clearance
        trunk tiles    = (N - N_baseline) * slot_pitch * lane_width
        spur tiles     = (N - N_baseline) * branch_spur * lane_width

    The model counts spatial corridor tiles only. Transport latency, congestion,
    crossings, and detailed lattice-surgery scheduling remain unmodeled.
    """
    if factory_count <= 0:
        raise RoutingInterconnectError("factory_count must be > 0.")
    if baseline_factory_count <= 0:
        raise RoutingInterconnectError(
            "baseline_factory_count must be > 0."
        )
    if factory_count < baseline_factory_count:
        raise RoutingInterconnectError(
            "factory_count must be >= baseline_factory_count."
        )
    if clearance_tiles < 0:
        raise RoutingInterconnectError("clearance_tiles must be >= 0.")
    if lane_width_tiles <= 0:
        raise RoutingInterconnectError("lane_width_tiles must be > 0.")
    if branch_spur_tiles < 0:
        raise RoutingInterconnectError("branch_spur_tiles must be >= 0.")

    span = square_envelope_factory_span(
        factory_tile_area=factory_tile_area
    )
    extra = factory_count - baseline_factory_count
    pitch = span + clearance_tiles

    trunk = extra * pitch * lane_width_tiles
    spurs = extra * branch_spur_tiles * lane_width_tiles
    total = trunk + spurs

    return RoutingInterconnectFootprint(
        model="manhattan_trunk_and_spur_v1",
        source=source,
        factory_count=factory_count,
        baseline_factory_count=baseline_factory_count,
        factory_tile_area=factory_tile_area,
        effective_factory_span_tiles=span,
        clearance_tiles=clearance_tiles,
        lane_width_tiles=lane_width_tiles,
        branch_spur_tiles=branch_spur_tiles,
        extra_factory_count=extra,
        slot_pitch_tiles=pitch,
        trunk_tiles=trunk,
        spur_tiles=spurs,
        total_routing_tiles=total,
    )
