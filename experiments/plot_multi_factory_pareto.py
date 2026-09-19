from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from experiments.multi_factory_pareto_search import run


def _plot_qubits_vs_risk(
    result: dict[str, object],
    *,
    output_path: Path,
) -> None:
    candidates = list(result["feasible_candidates"])
    frontier = list(result["pareto_frontier"])
    frontier_ids = {str(row["candidate_id"]) for row in frontier}

    dominated = [
        row
        for row in candidates
        if str(row["candidate_id"]) not in frontier_ids
    ]

    fig = plt.figure(figsize=(10, 6))
    ax = fig.add_subplot(111)

    if dominated:
        ax.scatter(
            [row["physical_qubits"] for row in dominated],
            [row["probability_any_starvation"] for row in dominated],
            marker="x",
            label="Dominated",
        )

    ax.scatter(
        [row["physical_qubits"] for row in frontier],
        [row["probability_any_starvation"] for row in frontier],
        marker="o",
        label="Pareto frontier",
    )

    references = {
        view["candidate_id"]
        for view in result["risk_target_views"].values()
        if view is not None
    }
    by_id = {
        str(row["candidate_id"]): row
        for row in frontier
    }
    for candidate_id in sorted(references):
        row = by_id[candidate_id]
        ax.annotate(
            candidate_id,
            (
                row["physical_qubits"],
                row["probability_any_starvation"],
            ),
        )

    ax.set_yscale("log")
    ax.set_xlabel("Physical qubits")
    ax.set_ylabel("P(any starvation)")
    ax.set_title("Multi-Factory Co-Design: Hardware vs Starvation Risk")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_startup_vs_risk(
    result: dict[str, object],
    *,
    output_path: Path,
) -> None:
    candidates = list(result["feasible_candidates"])
    frontier = list(result["pareto_frontier"])
    frontier_ids = {str(row["candidate_id"]) for row in frontier}

    dominated = [
        row
        for row in candidates
        if str(row["candidate_id"]) not in frontier_ids
    ]

    fig = plt.figure(figsize=(10, 6))
    ax = fig.add_subplot(111)

    if dominated:
        ax.scatter(
            [
                row["conservative_startup_seconds"] * 1000.0
                for row in dominated
            ],
            [row["probability_any_starvation"] for row in dominated],
            marker="x",
            label="Dominated",
        )

    ax.scatter(
        [
            row["conservative_startup_seconds"] * 1000.0
            for row in frontier
        ],
        [row["probability_any_starvation"] for row in frontier],
        marker="o",
        label="Pareto frontier",
    )

    references = {
        view["candidate_id"]
        for view in result["risk_target_views"].values()
        if view is not None
    }
    by_id = {
        str(row["candidate_id"]): row
        for row in frontier
    }
    for candidate_id in sorted(references):
        row = by_id[candidate_id]
        ax.annotate(
            candidate_id,
            (
                row["conservative_startup_seconds"] * 1000.0,
                row["probability_any_starvation"],
            ),
        )

    ax.set_yscale("log")
    ax.set_xlabel("Conservative startup latency (ms)")
    ax.set_ylabel("P(any starvation)")
    ax.set_title("Multi-Factory Co-Design: Startup vs Starvation Risk")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def render_multi_factory_pareto_plots(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    qubits = output_path / "multi_factory_qubits_vs_risk.png"
    startup = output_path / "multi_factory_startup_vs_risk.png"

    _plot_qubits_vs_risk(result, output_path=qubits)
    _plot_startup_vs_risk(result, output_path=startup)

    return {
        "qubits_vs_risk": str(qubits),
        "startup_vs_risk": str(startup),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_multi_factory_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/multi_factory_pareto",
    )
    args = parser.parse_args()

    result = run(args.config)
    paths = render_multi_factory_pareto_plots(
        result,
        output_dir=args.output_dir,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
