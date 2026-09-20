from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from experiments.m17b_beam_search import run


def plot_pareto(
    result: dict[str, object],
    *,
    output_path: str | Path,
) -> str:
    candidates = list(result["candidates"])
    frontier = list(result["pareto_frontier"])

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(9, 6))
    ax = fig.add_subplot(111)

    ax.scatter(
        [
            row["physical_qubits"]
            for row in candidates
        ],
        [
            row["stress_space_time_volume"]
            for row in candidates
        ],
        marker="o",
        label="M17B candidates",
    )
    ax.scatter(
        [
            row["physical_qubits"]
            for row in frontier
        ],
        [
            row["stress_space_time_volume"]
            for row in frontier
        ],
        marker="x",
        label="Pareto frontier",
    )

    for row in frontier:
        ax.annotate(
            f"s={float(row['corridor_sharing_degree']):.2f}",
            (
                row["physical_qubits"],
                row["stress_space_time_volume"],
            ),
            fontsize=8,
        )

    ax.set_xlabel("Physical qubits (fixed d)")
    ax.set_ylabel(
        "Stress-horizon space-time volume [qubit*s]"
    )
    ax.set_title(
        "M17B: spatial footprint vs deterministic temporal cost"
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)

    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/m17b_beam_materializer.yaml",
    )
    parser.add_argument(
        "--output",
        default="results/m17b/pareto_nphys_vs_stv.png",
    )
    args = parser.parse_args()

    result = run(args.config)
    print(
        plot_pareto(
            result,
            output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
