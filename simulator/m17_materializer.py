from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import heapq
import math
from typing import Iterable

from simulator.floorplanner import (
    Cell,
    FloorplanResult,
    PlacedBlock,
    RoutedConnection,
    TileShape,
    compact_raster_shape,
)
from simulator.m17_candidate import LayoutCandidateSpec


class M17MaterializerError(ValueError):
    """Raised when M17 beam materialization cannot produce a valid layout."""


@dataclass(frozen=True)
class MaterializedLayout:
    spec: LayoutCandidateSpec
    floorplan: FloorplanResult
    factory_paths: dict[int, tuple[Cell, ...]]
    shared_factory_route_cells: int
    factory_route_union_tiles: int
    actual_route_overlap_fraction: float
    max_factory_path_tiles: int
    mean_factory_path_tiles: float

    def to_dict(self) -> dict[str, object]:
        min_x, min_y, max_x, max_y = self.floorplan.bbox
        return {
            **self.spec.to_dict(),
            "shared_factory_route_cells": self.shared_factory_route_cells,
            "factory_route_union_tiles": self.factory_route_union_tiles,
            "actual_route_overlap_fraction": self.actual_route_overlap_fraction,
            "route_union_tiles": self.floorplan.route_union_tiles,
            "active_tiles": self.floorplan.active_tiles,
            "bbox_area_tiles": self.floorplan.bbox_area_tiles,
            "bbox_width_tiles": max_x - min_x + 1,
            "bbox_height_tiles": max_y - min_y + 1,
            "packing_density": self.floorplan.packing_density,
            "max_factory_path_tiles": self.max_factory_path_tiles,
            "mean_factory_path_tiles": self.mean_factory_path_tiles,
            "placements": [
                {
                    "name": p.name,
                    "role": p.role,
                    "x": p.x,
                    "y": p.y,
                    "width": p.shape.width,
                    "height": p.shape.height,
                    "tile_area": p.shape.tile_area,
                }
                for p in self.floorplan.placements
            ],
            "routes": [
                {
                    "name": r.name,
                    "source": r.source,
                    "target": r.target,
                    "path_tiles": len(r.path),
                }
                for r in self.floorplan.routes
            ],
        }


@dataclass(frozen=True)
class _PartialState:
    spec: LayoutCandidateSpec
    data_block: PlacedBlock
    buffer_block: PlacedBlock
    factory_shape: TileShape
    placements: tuple[PlacedBlock, ...]
    routes: tuple[RoutedConnection, ...]
    factory_route_counts: tuple[tuple[Cell, int], ...]
    next_factory_index: int

    @property
    def route_union(self) -> set[Cell]:
        return {
            cell
            for route in self.routes
            for cell in route.path
        }

    @property
    def factory_route_counter(self) -> Counter[Cell]:
        return Counter(dict(self.factory_route_counts))


def _occupied(placements: Iterable[PlacedBlock]) -> set[Cell]:
    result: set[Cell] = set()
    for placement in placements:
        result.update(placement.cells)
    return result


def _bbox(cells: Iterable[Cell]) -> tuple[int, int, int, int]:
    items = tuple(cells)
    if not items:
        raise M17MaterializerError("cannot compute bbox of no cells.")
    xs = [x for x, _ in items]
    ys = [y for _, y in items]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    min_x, min_y, max_x, max_y = bbox
    return (max_x - min_x + 1) * (max_y - min_y + 1)


def _collides(
    *,
    occupied: set[Cell],
    candidate: PlacedBlock,
    clearance_tiles: int,
) -> bool:
    candidate_cells = set(candidate.cells)
    for x, y in occupied:
        for dx in range(-clearance_tiles, clearance_tiles + 1):
            for dy in range(-clearance_tiles, clearance_tiles + 1):
                if (x + dx, y + dy) in candidate_cells:
                    return True
    return False


def _perimeter_neighbors(
    block: PlacedBlock,
    *,
    blocked: set[Cell],
) -> set[Cell]:
    own = set(block.cells)
    result: set[Cell] = set()
    for x, y in own:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cell = (x + dx, y + dy)
            if cell not in own and cell not in blocked:
                result.add(cell)
    return result


def _distance_to_targets(
    cell: Cell,
    targets: tuple[Cell, ...],
) -> int:
    x, y = cell
    return min(
        abs(x - tx) + abs(y - ty)
        for tx, ty in targets
    )


def _route_with_sharing_bias(
    *,
    source: PlacedBlock,
    target: PlacedBlock,
    placements: tuple[PlacedBlock, ...],
    existing_factory_routes: set[Cell],
    sharing_degree: float,
    search_margin_tiles: int,
) -> tuple[Cell, ...]:
    blocked = _occupied(placements)
    sources = _perimeter_neighbors(source, blocked=blocked)
    targets = _perimeter_neighbors(target, blocked=blocked)

    if not sources or not targets:
        raise M17MaterializerError(
            f"no route terminals for {source.name}."
        )

    geometry = blocked | sources | targets | existing_factory_routes
    min_x, min_y, max_x, max_y = _bbox(geometry)
    bounds = (
        min_x - search_margin_tiles,
        min_y - search_margin_tiles,
        max_x + search_margin_tiles,
        max_y + search_margin_tiles,
    )

    target_tuple = tuple(sorted(targets))
    reuse_cost = max(
        0.05,
        1.0 + (1.0 - sharing_degree) * 3.0 - sharing_degree * 0.95,
    )
    min_step_cost = min(1.0, reuse_cost)

    queue: list[tuple[float, float, int, int, Cell]] = []
    distance: dict[Cell, float] = {}
    previous: dict[Cell, Cell] = {}

    for cell in sorted(sources):
        distance[cell] = 0.0
        heapq.heappush(
            queue,
            (
                _distance_to_targets(cell, target_tuple) * min_step_cost,
                0.0,
                cell[1],
                cell[0],
                cell,
            ),
        )

    visited: set[Cell] = set()

    while queue:
        _, cost, _, _, current = heapq.heappop(queue)
        if current in visited:
            continue
        visited.add(current)

        if current in targets:
            path = [current]
            while current in previous:
                current = previous[current]
                path.append(current)
            path.reverse()
            return tuple(path)

        x, y = current
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (x + dx, y + dy)
            if not (
                bounds[0] <= neighbor[0] <= bounds[2]
                and bounds[1] <= neighbor[1] <= bounds[3]
            ):
                continue
            if neighbor in blocked:
                continue

            step_cost = (
                reuse_cost
                if neighbor in existing_factory_routes
                else 1.0
            )
            new_cost = cost + step_cost
            if new_cost >= distance.get(neighbor, math.inf):
                continue

            distance[neighbor] = new_cost
            previous[neighbor] = current
            heuristic = (
                _distance_to_targets(neighbor, target_tuple)
                * min_step_cost
            )
            heapq.heappush(
                queue,
                (
                    new_cost + heuristic,
                    new_cost,
                    neighbor[1],
                    neighbor[0],
                    neighbor,
                ),
            )

    raise M17MaterializerError(
        f"no route found from {source.name} to shared_buffer."
    )


def _anchor_candidates(
    *,
    buffer_block: PlacedBlock,
    factory_shape: TileShape,
    spec: LayoutCandidateSpec,
) -> tuple[Cell, ...]:
    bmin_x, bmin_y, bmax_x, bmax_y = buffer_block.bbox
    center_x = (bmin_x + bmax_x) // 2
    center_y = (bmin_y + bmax_y) // 2

    radius = spec.placement_radius_tiles
    clearance = spec.clearance_tiles
    fw = factory_shape.width
    fh = factory_shape.height

    variant_shift = (spec.anchor_rotation_index - 1) * max(
        1,
        min(fw, fh) // 2,
    )

    anchors = [
        (
            bmax_x + clearance + radius,
            center_y - fh // 2 + variant_shift,
        ),
        (
            center_x - fw // 2 + variant_shift,
            bmin_y - clearance - radius - fh,
        ),
        (
            bmin_x - clearance - radius - fw,
            center_y - fh // 2 - variant_shift,
        ),
        (
            center_x - fw // 2 - variant_shift,
            bmax_y + clearance + radius,
        ),
        (
            bmax_x + clearance + radius,
            bmin_y - clearance - radius - fh,
        ),
        (
            bmin_x - clearance - radius - fw,
            bmin_y - clearance - radius - fh,
        ),
        (
            bmin_x - clearance - radius - fw,
            bmax_y + clearance + radius,
        ),
        (
            bmax_x + clearance + radius,
            bmax_y + clearance + radius,
        ),
    ]

    rotation = spec.anchor_rotation_index % len(anchors)
    ordered = anchors[rotation:] + anchors[:rotation]
    return tuple(dict.fromkeys(ordered))


def _overlap_metrics(
    counter: Counter[Cell],
) -> tuple[int, int, float]:
    union_tiles = len(counter)
    shared_tiles = sum(count > 1 for count in counter.values())
    fraction = (
        shared_tiles / union_tiles
        if union_tiles
        else 0.0
    )
    return shared_tiles, union_tiles, fraction


def _partial_rank(
    state: _PartialState,
) -> tuple[float, int, int, int, str]:
    counter = state.factory_route_counter
    _, _, actual_overlap = _overlap_metrics(counter)
    overlap_error = abs(
        actual_overlap - state.spec.route_overlap_target_fraction
    )

    occupied = _occupied(state.placements)
    route_union = state.route_union
    bbox_area = _bbox_area(_bbox(occupied | route_union))
    max_path = max(
        (
            len(route.path)
            for route in state.routes
            if route.source.startswith("factory_")
        ),
        default=0,
    )

    return (
        round(overlap_error, 12),
        len(route_union),
        bbox_area,
        max_path,
        state.spec.candidate_id,
    )


def _select_diverse_beam(
    states: Iterable[_PartialState],
    *,
    beam_width: int,
) -> tuple[_PartialState, ...]:
    rows = sorted(states, key=_partial_rank)
    if not rows:
        raise M17MaterializerError(
            "beam expansion produced no valid states."
        )

    by_degree: dict[float, list[_PartialState]] = {}
    for row in rows:
        by_degree.setdefault(
            row.spec.corridor_sharing_degree,
            [],
        ).append(row)

    selected: list[_PartialState] = []
    selected_keys: set[tuple[str, tuple[tuple[str, int, int], ...]]] = set()

    def key(state: _PartialState) -> tuple[str, tuple[tuple[str, int, int], ...]]:
        geometry = tuple(
            (
                placement.name,
                placement.x,
                placement.y,
            )
            for placement in state.placements
        )
        return state.spec.candidate_id, geometry

    for degree in sorted(by_degree):
        state = by_degree[degree][0]
        selected.append(state)
        selected_keys.add(key(state))

    for state in rows:
        if len(selected) >= beam_width:
            break
        state_key = key(state)
        if state_key in selected_keys:
            continue
        selected.append(state)
        selected_keys.add(state_key)

    return tuple(selected[:beam_width])


def _initial_state(
    *,
    spec: LayoutCandidateSpec,
    data_block_tiles: int,
    shared_buffer_tiles: int,
    factory_tiles: int,
    search_margin_tiles: int,
) -> _PartialState:
    data_shape = compact_raster_shape(
        name="data_block",
        tile_area=data_block_tiles,
    )
    buffer_shape = compact_raster_shape(
        name="shared_buffer",
        tile_area=shared_buffer_tiles,
    )
    factory_shape = compact_raster_shape(
        name="factory",
        tile_area=factory_tiles,
    )

    data = PlacedBlock(
        name="data_block",
        role="data_block",
        shape=data_shape,
        x=0,
        y=0,
    )
    buffer_block = PlacedBlock(
        name="shared_buffer",
        role="shared_buffer",
        shape=buffer_shape,
        x=data_shape.width + spec.clearance_tiles,
        y=(data_shape.height - buffer_shape.height) // 2,
    )

    placements = (data, buffer_block)
    data_path = _route_with_sharing_bias(
        source=data,
        target=buffer_block,
        placements=placements,
        existing_factory_routes=set(),
        sharing_degree=0.0,
        search_margin_tiles=search_margin_tiles,
    )

    return _PartialState(
        spec=spec,
        data_block=data,
        buffer_block=buffer_block,
        factory_shape=factory_shape,
        placements=placements,
        routes=(
            RoutedConnection(
                name="data_to_buffer",
                source="data_block",
                target="shared_buffer",
                path=data_path,
            ),
        ),
        factory_route_counts=(),
        next_factory_index=1,
    )


def _expand_state(
    state: _PartialState,
    *,
    search_margin_tiles: int,
) -> tuple[_PartialState, ...]:
    occupied = _occupied(state.placements)
    existing_counter = state.factory_route_counter
    existing_factory_routes = set(existing_counter)

    expansions: list[_PartialState] = []

    for x, y in _anchor_candidates(
        buffer_block=state.buffer_block,
        factory_shape=state.factory_shape,
        spec=state.spec,
    ):
        factory = PlacedBlock(
            name=f"factory_{state.next_factory_index}",
            role="factory",
            shape=state.factory_shape,
            x=x,
            y=y,
        )
        if _collides(
            occupied=occupied,
            candidate=factory,
            clearance_tiles=state.spec.clearance_tiles,
        ):
            continue

        placements = (*state.placements, factory)
        try:
            path = _route_with_sharing_bias(
                source=factory,
                target=state.buffer_block,
                placements=placements,
                existing_factory_routes=existing_factory_routes,
                sharing_degree=state.spec.corridor_sharing_degree,
                search_margin_tiles=search_margin_tiles,
            )
        except M17MaterializerError:
            continue

        counter = existing_counter.copy()
        counter.update(path)

        route = RoutedConnection(
            name=f"{factory.name}_to_buffer",
            source=factory.name,
            target="shared_buffer",
            path=path,
        )
        expansions.append(
            _PartialState(
                spec=state.spec,
                data_block=state.data_block,
                buffer_block=state.buffer_block,
                factory_shape=state.factory_shape,
                placements=tuple(placements),
                routes=(*state.routes, route),
                factory_route_counts=tuple(sorted(counter.items())),
                next_factory_index=state.next_factory_index + 1,
            )
        )

    return tuple(expansions)


def _finalize(state: _PartialState) -> MaterializedLayout:
    block_cells = _occupied(state.placements)
    route_union = state.route_union
    active_cells = block_cells | route_union
    bbox = _bbox(active_cells)
    bbox_area = _bbox_area(bbox)

    counter = state.factory_route_counter
    shared_cells, factory_union, overlap_fraction = _overlap_metrics(
        counter
    )

    factory_routes = [
        route
        for route in state.routes
        if route.source.startswith("factory_")
    ]
    paths = {
        int(route.source.split("_", 1)[1]): route.path
        for route in factory_routes
    }
    path_lengths = [len(path) for path in paths.values()]

    floorplan = FloorplanResult(
        model="m17_diversity_beam_shared_route_astar_v1",
        block_shape_model="compact_raster_exact_area_v1",
        placement_objective=(
            "intent_overlap_error_then_route_union_then_bbox_then_path"
        ),
        clearance_tiles=state.spec.clearance_tiles,
        placements=state.placements,
        routes=state.routes,
        route_union_cells=tuple(sorted(route_union)),
        block_tiles=len(block_cells),
        route_union_tiles=len(route_union),
        active_tiles=len(active_cells),
        bbox=bbox,
        bbox_area_tiles=bbox_area,
        packing_density=len(active_cells) / bbox_area,
    )

    return MaterializedLayout(
        spec=state.spec,
        floorplan=floorplan,
        factory_paths=paths,
        shared_factory_route_cells=shared_cells,
        factory_route_union_tiles=factory_union,
        actual_route_overlap_fraction=overlap_fraction,
        max_factory_path_tiles=max(path_lengths, default=0),
        mean_factory_path_tiles=(
            sum(path_lengths) / len(path_lengths)
            if path_lengths
            else 0.0
        ),
    )


def materialize_diverse_beam(
    *,
    specs: Iterable[LayoutCandidateSpec],
    data_block_tiles: int,
    shared_buffer_tiles: int,
    factory_tiles: int,
    beam_width: int,
    search_margin_tiles: int,
) -> tuple[MaterializedLayout, ...]:
    specs = tuple(specs)
    if not specs:
        raise M17MaterializerError(
            "at least one candidate spec is required."
        )
    factory_counts = {
        spec.factory_count for spec in specs
    }
    if len(factory_counts) != 1:
        raise M17MaterializerError(
            "one beam run must use one factory_count."
        )
    if beam_width <= 0:
        raise M17MaterializerError("beam_width must be > 0.")

    factory_count = next(iter(factory_counts))
    states = tuple(
        _initial_state(
            spec=spec,
            data_block_tiles=data_block_tiles,
            shared_buffer_tiles=shared_buffer_tiles,
            factory_tiles=factory_tiles,
            search_margin_tiles=search_margin_tiles,
        )
        for spec in specs
    )

    for _ in range(factory_count):
        expanded = [
            child
            for state in states
            for child in _expand_state(
                state,
                search_margin_tiles=search_margin_tiles,
            )
        ]
        states = _select_diverse_beam(
            expanded,
            beam_width=beam_width,
        )

    layouts = tuple(_finalize(state) for state in states)

    surviving_degrees = {
        layout.spec.corridor_sharing_degree
        for layout in layouts
    }
    requested_degrees = {
        spec.corridor_sharing_degree
        for spec in specs
    }
    if not requested_degrees.issubset(surviving_degrees):
        missing = sorted(requested_degrees - surviving_degrees)
        raise M17MaterializerError(
            "diversity injection failed for sharing degrees: "
            f"{missing}"
        )

    return layouts
