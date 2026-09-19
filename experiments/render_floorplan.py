from __future__ import annotations

import argparse
from pathlib import Path
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from simulator.buffer_consumer import replicated_storage_tiles
from simulator.config import load_config
from simulator.floorplanner import build_greedy_floorplan


_CANDIDATE = re.compile(
    r"^N(?P<factories>\d+)_B(?P<buffer>\d+)_"
    r"(?P<phase>SYNC|STAG)_I(?P<initial>\d+)$"
)


def build_candidate_floorplan(
    *,
    config_path: str,
    candidate_id: str,
):
    match = _CANDIDATE.match(candidate_id)
    if match is None:
        raise ValueError(f"invalid candidate_id: {candidate_id}")

    config = load_config(config_path)
    resource = config["resource_model"]
    protocol = config["factories"]["protocol"]
    floor_cfg = resource["floorplanner"]
    buffer_cfg = resource["shared_buffer"]

    factories = int(match.group("factories"))
    capacity = int(match.group("buffer"))

    storage_tiles = replicated_storage_tiles(
        buffer_capacity_states=capacity,
        base_capacity_states=int(buffer_cfg["base_capacity_states"]),
        base_storage_tiles=int(buffer_cfg["base_storage_tiles"]),
    )

    return build_greedy_floorplan(
        factory_count=factories,
        data_block_tiles=int(resource["data_block"]["tiles"]["value"]),
        shared_buffer_tiles=storage_tiles,
        factory_tiles=int(protocol["distillation_tiles"]),
        clearance_tiles=int(floor_cfg["clearance_tiles"]),
        search_margin_tiles=int(floor_cfg["search_margin_tiles"]),
    )


def render_floorplan(
    *,
    config_path: str,
    candidate_id: str,
    output_path: str | Path,
) -> str:
    floorplan = build_candidate_floorplan(
        config_path=config_path,
        candidate_id=candidate_id,
    )

    min_x, min_y, max_x, max_y = floorplan.bbox
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    grid = np.zeros((height, width), dtype=int)

    for x, y in floorplan.route_union_cells:
        grid[y - min_y, x - min_x] = 1

    role_value = {
        "data_block": 2,
        "shared_buffer": 3,
        "factory": 4,
    }
    for placement in floorplan.placements:
        value = role_value[placement.role]
        for x, y in placement.cells:
            grid[y - min_y, x - min_x] = value

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(11, 6))
    ax = fig.add_subplot(111)
    ax.imshow(
        grid,
        origin="lower",
        interpolation="nearest",
        aspect="equal",
    )

    for placement in floorplan.placements:
        x0, y0, x1, y1 = placement.bbox
        ax.text(
            ((x0 + x1) / 2) - min_x,
            ((y0 + y1) / 2) - min_y,
            placement.name,
            ha="center",
            va="center",
        )

    ax.set_title(
        f"{candidate_id} — greedy 2D FTQC floorplan + A* routing"
    )
    ax.set_xlabel("tile x")
    ax.set_ylabel("tile y")
    ax.set_xticks(range(width))
    ax.set_yticks(range(height))
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)

    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=(
            "configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml"
        ),
    )
    parser.add_argument(
        "--candidate",
        default="N2_B048_STAG_I012",
    )
    parser.add_argument(
        "--output",
        default="results/floorplans/N2_B048_STAG_I012.png",
    )
    args = parser.parse_args()

    print(
        render_floorplan(
            config_path=args.config,
            candidate_id=args.candidate,
            output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
