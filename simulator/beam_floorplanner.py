from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Iterable

from simulator.floorplanner import (
    Cell,
    FloorplanResult,
    PlacedBlock,
    RoutedConnection,
    compact_raster_shape,
)


class BeamFloorplannerError(ValueError):
    """Raised when beam-search floorplanning inputs are invalid."""


@dataclass(frozen=True)
class LayoutCandidate:
    candidate_id: str
    factory_count: int
    sharing_target: float
    floorplan: FloorplanResult
    factory_route_union_tiles: int
    shared_factory_route_cells: int
    max_factory_route_multiplicity: int
    factory_route_incidence_tiles: int
    sharing_fraction: float
    max_factory_path_tiles: int
    mean_factory_path_tiles: float
    bbox_area_tiles: int
    active_tiles: int

    @property
    def route_savings_vs_disjoint_incidence(self) -> int:
        return (
            self.factory_route_incidence_tiles
            - self.factory_route_union_tiles
        )


@dataclass(frozen=True)
class _PartialLayout:
    placements: tuple[PlacedBlock, ...]
    data_buffer_route: tuple[Cell, ...]
    factory_routes: tuple[tuple[Cell, ...], ...]


def _bbox(cells: Iterable[Cell]) -> tuple[int, int, int, int]:
    items = tuple(cells)
    if not items:
        raise BeamFloorplannerError("cannot bound an empty cell set.")
    xs = [x for x, _ in items]
    ys = [y for _, y in items]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    min_x, min_y, max_x, max_y = bbox
    return (max_x - min_x + 1) * (max_y - min_y + 1)


def _occupied(placements: Iterable[PlacedBlock]) -> set[Cell]:
    cells: set[Cell] = set()
    for placement in placements:
        cells.update(placement.cells)
    return cells


def _collides_with_clearance(
    *,
    occupied: set[Cell],
    candidate_cells: Iterable[Cell],
    clearance_tiles: int,
) -> bool:
    candidate = set(candidate_cells)
    if clearance_tiles < 0:
        raise BeamFloorplannerError("clearance_tiles must be >= 0.")
    if not candidate:
        return True

    if occupied & candidate:
        return True

    if clearance_tiles == 0:
        return False

    for x, y in occupied:
        for dx in range(-clearance_tiles, clearance_tiles + 1):
            for dy in range(-clearance_tiles, clearance_tiles + 1):
                if (x + dx, y + dy) in candidate:
                    return True
    return False


def _perimeter_neighbors(
    placement: PlacedBlock,
    *,
    blocked: set[Cell],
) -> set[Cell]:
    own = set(placement.cells)
    neighbors: set[Cell] = set()
    for x, y in own:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cell = (x + dx, y + dy)
            if cell not in own and cell not in blocked:
                neighbors.add(cell)
    return neighbors


def _candidate_anchors(
    *,
    occupied_bbox: tuple[int, int, int, int],
    buffer_block: PlacedBlock,
    factory_width: int,
    factory_height: int,
    clearance_tiles: int,
) -> tuple[Cell, ...]:
    min_x, min_y, max_x, max_y = occupied_bbox
    gap = clearance_tiles

    anchors: set[Cell] = {
        (
            buffer_block.x + buffer_block.shape.width + gap,
            buffer_block.y,
        ),
        (
            buffer_block.x - factory_width - gap,
            buffer_block.y,
        ),
        (
            buffer_block.x,
            buffer_block.y - factory_height - gap,
        ),
        (
            buffer_block.x,
            buffer_block.y + buffer_block.shape.height + gap,
        ),
    }

    y_step = max(1, (factory_height + gap) // 2)
    x_step = max(1, (factory_width + gap) // 2)

    for y in range(
        min_y - 2 * (factory_height + gap),
        max_y + 2 * (factory_height + gap) + 1,
        y_step,
    ):
        anchors.add((max_x + gap + 1, y))
        anchors.add((min_x - gap - factory_width, y))

    for x in range(
        min_x - 2 * (factory_width + gap),
        max_x + 2 * (factory_width + gap) + 1,
        x_step,
    ):
        anchors.add((x, min_y - gap - factory_height))
        anchors.add((x, max_y + gap + 1))

    return tuple(sorted(anchors, key=lambda p: (p[1], p[0])))


def _manhattan_to_targets(
    cell: Cell,
    targets: tuple[Cell, ...],
) -> int:
    x, y = cell
    return min(abs(x - tx) + abs(y - ty) for tx, ty in targets)


def _weighted_astar_route(
    *,
    sources: set[Cell],
    targets: set[Cell],
    blocked: set[Cell],
    existing_factory_route_cells: set[Cell],
    bounds: tuple[int, int, int, int],
    sharing_target: float,
) -> tuple[Cell, ...] | None:
    if not 0.0 <= sharing_target <= 1.0:
        raise BeamFloorplannerError(
            "sharing_target must be in [0, 1]."
        )
    if not sources or not targets:
        return None

    # A low sharing target explicitly discourages reuse; a high target makes
    # already-routed factory corridor cells cheap. New cells always cost 1.
    existing_cost = 3.0 - 2.75 * sharing_target

    target_tuple = tuple(sorted(targets))
    min_x, min_y, max_x, max_y = bounds

    queue: list[
        tuple[float, float, int, int, Cell]
    ] = []
    distance: dict[Cell, float] = {}
    came_from: dict[Cell, Cell] = {}

    for source in sorted(sources):
        if source in blocked:
            continue
        distance[source] = 0.0
        heapq.heappush(
            queue,
            (
                float(_manhattan_to_targets(source, target_tuple)),
                0.0,
                source[1],
                source[0],
                source,
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
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return tuple(path)

        x, y = current
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (x + dx, y + dy)
            if not (
                min_x <= neighbor[0] <= max_x
                and min_y <= neighbor[1] <= max_y
            ):
                continue
            if neighbor in blocked:
                continue

            step_cost = (
                existing_cost
                if neighbor in existing_factory_route_cells
                else 1.0
            )
            new_cost = cost + step_cost
            if new_cost >= distance.get(neighbor, math.inf):
                continue

            distance[neighbor] = new_cost
            came_from[neighbor] = current
            heuristic = _manhattan_to_targets(
                neighbor,
                target_tuple,
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

    return None


def _route_between(
    *,
    source: PlacedBlock,
    target: PlacedBlock,
    placements: tuple[PlacedBlock, ...],
    existing_factory_route_cells: set[Cell],
    search_margin_tiles: int,
    sharing_target: float,
) -> tuple[Cell, ...]:
    blocked = _occupied(placements)
    sources = _perimeter_neighbors(source, blocked=blocked)
    targets = _perimeter_neighbors(target, blocked=blocked)

    search_cells = blocked | sources | targets
    if existing_factory_route_cells:
        search_cells |= existing_factory_route_cells

    min_x, min_y, max_x, max_y = _bbox(search_cells)
    bounds = (
        min_x - search_margin_tiles,
        min_y - search_margin_tiles,
        max_x + search_margin_tiles,
        max_y + search_margin_tiles,
    )

    path = _weighted_astar_route(
        sources=sources,
        targets=targets,
        blocked=blocked,
        existing_factory_route_cells=existing_factory_route_cells,
        bounds=bounds,
        sharing_target=sharing_target,
    )
    if path is None:
        raise BeamFloorplannerError(
            f"no route from {source.name} to {target.name}."
        )
    return path


def _route_statistics(
    routes: tuple[tuple[Cell, ...], ...],
) -> tuple[int, int, int, int, float]:
    multiplicity: dict[Cell, int] = {}
    incidence = 0

    for route in routes:
        incidence += len(route)
        for cell in set(route):
            multiplicity[cell] = multiplicity.get(cell, 0) + 1

    union_tiles = len(multiplicity)
    shared_cells = sum(
        count > 1 for count in multiplicity.values()
    )
    max_multiplicity = max(multiplicity.values(), default=0)
    sharing_fraction = (
        0.0
        if incidence == 0
        else max(0.0, 1.0 - union_tiles / incidence)
    )

    return (
        union_tiles,
        shared_cells,
        max_multiplicity,
        incidence,
        sharing_fraction,
    )


def _partial_signature(
    partial: _PartialLayout,
) -> tuple[object, ...]:
    factory_placements = tuple(
        (
            placement.x,
            placement.y,
            placement.shape.width,
            placement.shape.height,
        )
        for placement in partial.placements
        if placement.role == "factory"
    )
    routes = tuple(
        tuple(route)
        for route in partial.factory_routes
    )
    return factory_placements, routes


def _partial_score(
    partial: _PartialLayout,
    *,
    sharing_target: float,
) -> tuple[float, int, int, int, int, tuple[object, ...]]:
    (
        union_tiles,
        _shared_cells,
        max_multiplicity,
        _incidence,
        sharing_fraction,
    ) = _route_statistics(partial.factory_routes)

    all_cells = _occupied(partial.placements)
    all_cells.update(partial.data_buffer_route)
    for route in partial.factory_routes:
        all_cells.update(route)

    bbox_area = _bbox_area(_bbox(all_cells))
    max_path = max(
        (len(route) for route in partial.factory_routes),
        default=0,
    )

    return (
        abs(sharing_fraction - sharing_target),
        union_tiles,
        bbox_area,
        max_path,
        max_multiplicity,
        _partial_signature(partial),
    )


def _floorplan_from_partial(
    partial: _PartialLayout,
    *,
    clearance_tiles: int,
) -> FloorplanResult:
    routes: list[RoutedConnection] = [
        RoutedConnection(
            name="data_to_buffer",
            source="data_block",
            target="shared_buffer",
            path=partial.data_buffer_route,
        )
    ]

    for index, route in enumerate(
        partial.factory_routes,
        start=1,
    ):
        routes.append(
            RoutedConnection(
                name=f"factory_{index}_to_buffer",
                source=f"factory_{index}",
                target="shared_buffer",
                path=route,
            )
        )

    route_union: set[Cell] = set(partial.data_buffer_route)
    for route in partial.factory_routes:
        route_union.update(route)

    block_cells = _occupied(partial.placements)
    active = block_cells | route_union
    bbox = _bbox(active)
    bbox_area = _bbox_area(bbox)

    return FloorplanResult(
        model="beam_search_weighted_astar_v1",
        block_shape_model="compact_raster_exact_area_v1",
        placement_objective=(
            "sharing_target_then_route_union_then_bbox_then_max_path"
        ),
        clearance_tiles=clearance_tiles,
        placements=partial.placements,
        routes=tuple(routes),
        route_union_cells=tuple(sorted(route_union)),
        block_tiles=len(block_cells),
        route_union_tiles=len(route_union),
        active_tiles=len(block_cells) + len(route_union),
        bbox=bbox,
        bbox_area_tiles=bbox_area,
        packing_density=(
            (len(block_cells) + len(route_union)) / bbox_area
        ),
    )


def generate_layout_candidates(
    *,
    factory_count: int,
    data_block_tiles: int,
    shared_buffer_tiles: int,
    factory_tiles: int,
    sharing_target: float,
    beam_width: int = 8,
    final_candidates: int = 3,
    clearance_tiles: int = 1,
    search_margin_tiles: int = 24,
) -> tuple[LayoutCandidate, ...]:
    """
    Generate diverse physical layouts with deterministic beam search.

    sharing_target controls the routing bias:
      0.0 -> avoid existing factory corridors when alternatives exist
      1.0 -> strongly prefer existing factory corridors

    The beam score also tries to keep the achieved sharing fraction close to
    sharing_target, so the parameter is measurable rather than merely cosmetic.
    """
    if factory_count <= 0:
        raise BeamFloorplannerError("factory_count must be > 0.")
    if beam_width <= 0:
        raise BeamFloorplannerError("beam_width must be > 0.")
    if final_candidates <= 0:
        raise BeamFloorplannerError("final_candidates must be > 0.")
    if not 0.0 <= sharing_target <= 1.0:
        raise BeamFloorplannerError(
            "sharing_target must be in [0, 1]."
        )

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
        x=data_shape.width + clearance_tiles,
        y=(data_shape.height - buffer_shape.height) // 2,
    )

    base_placements = (data, buffer_block)
    data_buffer_route = _route_between(
        source=data,
        target=buffer_block,
        placements=base_placements,
        existing_factory_route_cells=set(),
        search_margin_tiles=search_margin_tiles,
        sharing_target=0.5,
    )

    beam: list[_PartialLayout] = [
        _PartialLayout(
            placements=base_placements,
            data_buffer_route=data_buffer_route,
            factory_routes=(),
        )
    ]

    for factory_index in range(1, factory_count + 1):
        expanded: list[_PartialLayout] = []

        for partial in beam:
            occupied = _occupied(partial.placements)
            anchors = _candidate_anchors(
                occupied_bbox=_bbox(occupied),
                buffer_block=buffer_block,
                factory_width=factory_shape.width,
                factory_height=factory_shape.height,
                clearance_tiles=clearance_tiles,
            )
            existing_factory_routes = {
                cell
                for route in partial.factory_routes
                for cell in route
            }

            for x, y in anchors:
                factory = PlacedBlock(
                    name=f"factory_{factory_index}",
                    role="factory",
                    shape=factory_shape,
                    x=x,
                    y=y,
                )
                if _collides_with_clearance(
                    occupied=occupied,
                    candidate_cells=factory.cells,
                    clearance_tiles=clearance_tiles,
                ):
                    continue

                placements = tuple(
                    (*partial.placements, factory)
                )
                try:
                    route = _route_between(
                        source=factory,
                        target=buffer_block,
                        placements=placements,
                        existing_factory_route_cells=(
                            existing_factory_routes
                        ),
                        search_margin_tiles=search_margin_tiles,
                        sharing_target=sharing_target,
                    )
                except BeamFloorplannerError:
                    continue

                expanded.append(
                    _PartialLayout(
                        placements=placements,
                        data_buffer_route=partial.data_buffer_route,
                        factory_routes=tuple(
                            (*partial.factory_routes, route)
                        ),
                    )
                )

        if not expanded:
            raise BeamFloorplannerError(
                f"no valid placements for factory {factory_index}."
            )

        deduplicated: dict[
            tuple[object, ...],
            _PartialLayout,
        ] = {}
        for partial in expanded:
            signature = _partial_signature(partial)
            deduplicated.setdefault(signature, partial)

        beam = sorted(
            deduplicated.values(),
            key=lambda partial: _partial_score(
                partial,
                sharing_target=sharing_target,
            ),
        )[:beam_width]

    finalists = sorted(
        beam,
        key=lambda partial: _partial_score(
            partial,
            sharing_target=sharing_target,
        ),
    )[:final_candidates]

    results: list[LayoutCandidate] = []

    for rank, partial in enumerate(finalists, start=1):
        floorplan = _floorplan_from_partial(
            partial,
            clearance_tiles=clearance_tiles,
        )
        (
            union_tiles,
            shared_cells,
            max_multiplicity,
            incidence,
            sharing_fraction,
        ) = _route_statistics(partial.factory_routes)

        path_lengths = [
            len(route)
            for route in partial.factory_routes
        ]
        candidate_id = (
            f"N{factory_count}_S{sharing_target:.2f}_"
            f"R{rank:02d}"
        )

        results.append(
            LayoutCandidate(
                candidate_id=candidate_id,
                factory_count=factory_count,
                sharing_target=sharing_target,
                floorplan=floorplan,
                factory_route_union_tiles=union_tiles,
                shared_factory_route_cells=shared_cells,
                max_factory_route_multiplicity=max_multiplicity,
                factory_route_incidence_tiles=incidence,
                sharing_fraction=sharing_fraction,
                max_factory_path_tiles=max(path_lengths),
                mean_factory_path_tiles=(
                    sum(path_lengths) / len(path_lengths)
                ),
                bbox_area_tiles=floorplan.bbox_area_tiles,
                active_tiles=floorplan.active_tiles,
            )
        )

    return tuple(results)


def candidate_summary(
    candidate: LayoutCandidate,
) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "factory_count": candidate.factory_count,
        "sharing_target": candidate.sharing_target,
        "sharing_fraction": candidate.sharing_fraction,
        "factory_route_union_tiles": (
            candidate.factory_route_union_tiles
        ),
        "factory_route_incidence_tiles": (
            candidate.factory_route_incidence_tiles
        ),
        "route_savings_vs_disjoint_incidence": (
            candidate.route_savings_vs_disjoint_incidence
        ),
        "shared_factory_route_cells": (
            candidate.shared_factory_route_cells
        ),
        "max_factory_route_multiplicity": (
            candidate.max_factory_route_multiplicity
        ),
        "max_factory_path_tiles": (
            candidate.max_factory_path_tiles
        ),
        "mean_factory_path_tiles": (
            candidate.mean_factory_path_tiles
        ),
        "bbox_area_tiles": candidate.bbox_area_tiles,
        "active_tiles": candidate.active_tiles,
        "placements": [
            {
                "name": placement.name,
                "role": placement.role,
                "x": placement.x,
                "y": placement.y,
                "width": placement.shape.width,
                "height": placement.shape.height,
                "tile_area": placement.shape.tile_area,
            }
            for placement in candidate.floorplan.placements
        ],
        "factory_routes": [
            {
                "source": route.source,
                "target": route.target,
                "path_tiles": len(route.path),
            }
            for route in candidate.floorplan.routes
            if route.source.startswith("factory_")
        ],
    }
