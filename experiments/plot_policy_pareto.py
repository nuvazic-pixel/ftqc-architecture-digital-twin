from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from experiments.policy_pareto_search import run


def _plot_risk_vs_qubits(
    result: dict[str, object],
    *,
    output_path: Path,
) -> None:
    candidates = list(result["feasible_candidates"])
    frontier = list(result["pareto_frontier"])
    frontier_ids = {str(row["candidate_id"]) for row in frontier}

    dominated = [
        row for row in candidates
        if str(row["candidate_id"]) not in frontier_ids
    ]

    fig = plt.figure(figsize=(9, 6))
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

    reference_ids = {
        view["candidate_id"]
        for view in result["risk_target_views"].values()
        if view is not None
    }
    by_id = {str(row["candidate_id"]): row for row in frontier}
    for candidate_id in sorted(reference_ids):
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
    ax.set_title("Prefill Policy Pareto: Hardware vs Starvation Risk")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _plot_risk_vs_prefill(
    result: dict[str, object],
    *,
    output_path: Path,
) -> None:
    candidates = list(result["feasible_candidates"])
    frontier = list(result["pareto_frontier"])
    frontier_ids = {str(row["candidate_id"]) for row in frontier}

    dominated = [
        row for row in candidates
        if str(row["candidate_id"]) not in frontier_ids
    ]

    fig = plt.figure(figsize=(9, 6))
    ax = fig.add_subplot(111)

    if dominated:
        ax.scatter(
            [row["expected_prefill_milliseconds"] for row in dominated],
            [row["probability_any_starvation"] for row in dominated],
            marker="x",
            label="Dominated",
        )

    ax.scatter(
        [row["expected_prefill_milliseconds"] for row in frontier],
        [row["probability_any_starvation"] for row in frontier],
        marker="o",
        label="Pareto frontier",
    )

    reference_ids = {
        view["candidate_id"]
        for view in result["risk_target_views"].values()
        if view is not None
    }
    by_id = {str(row["candidate_id"]): row for row in frontier}
    for candidate_id in sorted(reference_ids):
        row = by_id[candidate_id]
        ax.annotate(
            candidate_id,
            (
                row["expected_prefill_milliseconds"],
                row["probability_any_starvation"],
            ),
        )

    ax.set_yscale("log")
    ax.set_xlabel("Expected prefill latency (ms)")
    ax.set_ylabel("P(any starvation)")
    ax.set_title("Prefill Policy Pareto: Startup Latency vs Starvation Risk")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def render_policy_pareto_plots(
    result: dict[str, object],
    *,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    qubits_path = output_path / "pareto_qubits_vs_risk.png"
    prefill_path = output_path / "pareto_prefill_vs_risk.png"

    _plot_risk_vs_qubits(result, output_path=qubits_path)
    _plot_risk_vs_prefill(result, output_path=prefill_path)

    return {
        "qubits_vs_risk": str(qubits_path),
        "prefill_vs_risk": str(prefill_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/litinski_policy_pareto_10mT.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="results/policy_pareto",
    )
    args = parser.parse_args()

    result = run(args.config)
    paths = render_policy_pareto_plots(
        result,
        output_dir=args.output_dir,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
