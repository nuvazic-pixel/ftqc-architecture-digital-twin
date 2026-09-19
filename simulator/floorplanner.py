from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Iterable


class FloorplannerError(ValueError):
    """Raised when deterministic floorplanning inputs are invalid."""


Cell = tuple[int, int]


@dataclass(frozen=True)
class TileShape:
    name: str
    tile_area: int
    width: int
    height: int
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class PlacedBlock:
    name: str
    role: str
    shape: TileShape
    x: int
    y: int

    @property
    def cells(self) -> tuple[Cell, ...]:
        return tuple(
            (self.x + dx, self.y + dy)
            for dx, dy in self.shape.cells
        )

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (
            self.x,
            self.y,
            self.x + self.shape.width - 1,
            self.y + self.shape.height - 1,
        )


@dataclass(frozen=True)
class RoutedConnection:
    name: str
    source: str
    target: str
    path: tuple[Cell, ...]


@dataclass(frozen=True)
class FloorplanResult:
    model: str
    block_shape_model: str
    placement_objective: str
    clearance_tiles: int
    placements: tuple[PlacedBlock, ...]
    routes: tuple[RoutedConnection, ...]
    route_union_cells: tuple[Cell, ...]
    block_tiles: int
    route_union_tiles: int
    active_tiles: int
    bbox: tuple[int, int, int, int]
    bbox_area_tiles: int
    packing_density: float


def compact_raster_shape(*, name: str, tile_area: int) -> TileShape:
    """
    Deterministic exact-area compact raster.

    The envelope width is ceil(sqrt(area)); rows are filled left-to-right until
    exactly tile_area cells are occupied. This is a reproducible geometry proxy,
    not a literature claim about the exact polygon of a named logical block.
    """
    if tile_area <= 0:
        raise FloorplannerError("tile_area must be > 0.")

    width = math.ceil(math.sqrt(tile_area))
    height = math.ceil(tile_area / width)

    cells: list[Cell] = []
    for y in range(height):
        for x in range(width):
            if len(cells) == tile_area:
                break
            cells.append((x, y))

    return TileShape(
        name=name,
        tile_area=tile_area,
        width=width,
        height=height,
        cells=tuple(cells),
    )


def _bbox(cells: Iterable[Cell]) -> tuple[int, int, int, int]:
    items = tuple(cells)
    if not items:
        raise FloorplannerError("cannot compute a bounding box of no cells.")

    xs = [cell[0] for cell in items]
    ys = [cell[1] for cell in items]
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
    if clearance_tiles < 0:
        raise FloorplannerError("clearance_tiles must be >= 0.")

    candidate = set(candidate_cells)
    if not candidate:
        raise FloorplannerError("candidate block must contain at least one cell.")

    if clearance_tiles == 0:
        return bool(occupied & candidate)

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


def _manhattan_to_targets(cell: Cell, targets: tuple[Cell, ...]) -> int:
    x, y = cell
    return min(abs(x - tx) + abs(y - ty) for tx, ty in targets)


def _astar_route(
    *,
    sources: set[Cell],
    targets: set[Cell],
    blocked: set[Cell],
    bounds: tuple[int, int, int, int],
) -> tuple[Cell, ...] | None:
    if not sources or not targets:
        return None

    target_tuple = tuple(sorted(targets))
    min_x, min_y, max_x, max_y = bounds

    queue: list[tuple[int, int, int, int, Cell]] = []
    distance: dict[Cell, int] = {}
    came_from: dict[Cell, Cell] = {}

    for source in sorted(sources):
        if source in blocked:
            continue
        distance[source] = 0
        heapq.heappush(
            queue,
            (
                _manhattan_to_targets(source, target_tuple),
                0,
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

            new_cost = cost + 1
            if new_cost >= distance.get(neighbor, math.inf):
                continue

            distance[neighbor] = new_cost
            came_from[neighbor] = current
            heuristic = _manhattan_to_targets(neighbor, target_tuple)
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
    search_margin_tiles: int,
) -> tuple[Cell, ...]:
    if search_margin_tiles <= 0:
        raise FloorplannerError("search_margin_tiles must be > 0.")

    blocked = _occupied(placements)
    sources = _perimeter_neighbors(source, blocked=blocked)
    targets = _perimeter_neighbors(target, blocked=blocked)

    search_cells = blocked | sources | targets
    min_x, min_y, max_x, max_y = _bbox(search_cells)
    bounds = (
        min_x - search_margin_tiles,
        min_y - search_margin_tiles,
        max_x + search_margin_tiles,
        max_y + search_margin_tiles,
    )

    path = _astar_route(
        sources=sources,
        targets=targets,
        blocked=blocked,
        bounds=bounds,
    )
    if path is None:
        raise FloorplannerError(
            f"no route found from {source.name} to {target.name}."
        )
    return path


def _candidate_anchors(
    *,
    occupied_bbox: tuple[int, int, int, int],
    buffer_block: PlacedBlock,
    factory_shape: TileShape,
    clearance_tiles: int,
) -> set[Cell]:
    min_x, min_y, max_x, max_y = occupied_bbox
    gap = clearance_tiles

    anchors: set[Cell] = {
        (
            buffer_block.x + buffer_block.shape.width + gap,
            buffer_block.y,
        ),
        (
            buffer_block.x - factory_shape.width - gap,
            buffer_block.y,
        ),
        (
            buffer_block.x,
            buffer_block.y - factory_shape.height - gap,
        ),
        (
            buffer_block.x,
            buffer_block.y + buffer_block.shape.height + gap,
        ),
    }

    y_step = max(1, (factory_shape.height + gap) // 2)
    x_step = max(1, (factory_shape.width + gap) // 2)

    right_x = max_x + gap + 1
    left_x = min_x - gap - factory_shape.width
    y_start = min_y - 2 * (factory_shape.height + gap)
    y_stop = max_y + 2 * (factory_shape.height + gap)

    for y in range(y_start, y_stop + 1, y_step):
        anchors.add((right_x, y))
        anchors.add((left_x, y))

    top_y = min_y - gap - factory_shape.height
    bottom_y = max_y + gap + 1
    x_start = min_x - 2 * (factory_shape.width + gap)
    x_stop = max_x + 2 * (factory_shape.width + gap)

    for x in range(x_start, x_stop + 1, x_step):
        anchors.add((x, top_y))
        anchors.add((x, bottom_y))

    return anchors


def build_greedy_floorplan(
    *,
    factory_count: int,
    data_block_tiles: int,
    shared_buffer_tiles: int,
    factory_tiles: int,
    clearance_tiles: int = 1,
    search_margin_tiles: int = 24,
) -> FloorplanResult:
    """
    Deterministic 2D placement + A* routing model.

    Placement sequence:
      1. compact-raster data block at origin;
      2. compact-raster shared buffer to its right;
      3. factories placed one at a time by greedy candidate search.

    Candidate score is lexicographic:
      route-union tiles -> bounding-box area -> new path length -> anchor offset.

    Existing routing cells are shareable and are not obstacles. Logical blocks
    are obstacles. This models corridor reuse but not congestion/capacity.
    """
    if factory_count <= 0:
        raise FloorplannerError("factory_count must be > 0.")
    if clearance_tiles < 0:
        raise FloorplannerError("clearance_tiles must be >= 0.")

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

    buffer_x = data_shape.width + clearance_tiles
    buffer_y = (data_shape.height - buffer_shape.height) // 2
    buffer_block = PlacedBlock(
        name="shared_buffer",
        role="shared_buffer",
        shape=buffer_shape,
        x=buffer_x,
        y=buffer_y,
    )

    placements: list[PlacedBlock] = [data, buffer_block]

    data_to_buffer = _route_between(
        source=data,
        target=buffer_block,
        placements=tuple(placements),
        search_margin_tiles=search_margin_tiles,
    )
    routes: list[RoutedConnection] = [
        RoutedConnection(
            name="data_to_buffer",
            source=data.name,
            target=buffer_block.name,
            path=data_to_buffer,
        )
    ]
    route_union = set(data_to_buffer)

    for index in range(factory_count):
        occupied = _occupied(placements)
        occupied_bbox = _bbox(occupied)
        candidates: list[
            tuple[
                tuple[int, int, int, int, int, int],
                PlacedBlock,
                tuple[Cell, ...],
            ]
        ] = []

        anchors = _candidate_anchors(
            occupied_bbox=occupied_bbox,
            buffer_block=buffer_block,
            factory_shape=factory_shape,
            clearance_tiles=clearance_tiles,
        )

        for x, y in sorted(anchors):
            candidate = PlacedBlock(
                name=f"factory_{index + 1}",
                role="factory",
                shape=factory_shape,
                x=x,
                y=y,
            )

            if _collides_with_clearance(
                occupied=occupied,
                candidate_cells=candidate.cells,
                clearance_tiles=clearance_tiles,
            ):
                continue

            candidate_placements = tuple((*placements, candidate))
            try:
                path = _route_between(
                    source=candidate,
                    target=buffer_block,
                    placements=candidate_placements,
                    search_margin_tiles=search_margin_tiles,
                )
            except FloorplannerError:
                continue

            new_route_union = route_union | set(path)
            all_cells = occupied | set(candidate.cells) | new_route_union
            candidate_bbox = _bbox(all_cells)
            area = _bbox_area(candidate_bbox)
            anchor_offset = (
                abs(candidate.x - buffer_block.x)
                + abs(candidate.y - buffer_block.y)
            )

            score = (
                len(new_route_union),
                area,
                len(path),
                anchor_offset,
                candidate.y,
                candidate.x,
            )
            candidates.append((score, candidate, path))

        if not candidates:
            raise FloorplannerError(
                f"no valid placement found for factory_{index + 1}."
            )

        candidates.sort(key=lambda item: item[0])
        _, chosen, path = candidates[0]
        placements.append(chosen)
        route_union.update(path)
        routes.append(
            RoutedConnection(
                name=f"{chosen.name}_to_buffer",
                source=chosen.name,
                target=buffer_block.name,
                path=path,
            )
        )

    block_cells = _occupied(placements)
    all_active = block_cells | route_union
    result_bbox = _bbox(all_active)
    bbox_area = _bbox_area(result_bbox)
    active_tiles = len(block_cells) + len(route_union)

    return FloorplanResult(
        model="greedy_compact_raster_astar_v1",
        block_shape_model="compact_raster_exact_area_v1",
        placement_objective=(
            "min_route_union_then_bbox_then_path_then_anchor_offset"
        ),
        clearance_tiles=clearance_tiles,
        placements=tuple(placements),
        routes=tuple(routes),
        route_union_cells=tuple(sorted(route_union)),
        block_tiles=len(block_cells),
        route_union_tiles=len(route_union),
        active_tiles=active_tiles,
        bbox=result_bbox,
        bbox_area_tiles=bbox_area,
        packing_density=active_tiles / bbox_area,
    )


def placement_summaries(
    floorplan: FloorplanResult,
) -> list[dict[str, object]]:
    return [
        {
            "name": placement.name,
            "role": placement.role,
            "x": placement.x,
            "y": placement.y,
            "width": placement.shape.width,
            "height": placement.shape.height,
            "tile_area": placement.shape.tile_area,
        }
        for placement in floorplan.placements
    ]


def route_summaries(
    floorplan: FloorplanResult,
) -> list[dict[str, object]]:
    return [
        {
            "name": route.name,
            "source": route.source,
            "target": route.target,
            "path_tiles": len(route.path),
        }
        for route in floorplan.routes
    ]
