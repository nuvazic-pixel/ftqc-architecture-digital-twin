from __future__ import annotations

from pathlib import Path

import pytest

from experiments.plot_policy_pareto import render_policy_pareto_plots
from experiments.policy_pareto_search import run, write_outputs
from metrics.pareto import Objective, ParetoError, dominates, pareto_partition


@pytest.fixture(scope="module")
def policy_result() -> dict[str, object]:
    return run("configs/litinski_policy_pareto_10mT.yaml")


def test_mixed_direction_pareto_dominance():
    objectives = (
        Objective("hardware", "min"),
        Objective("startup", "min"),
        Objective("survival_log10", "max"),
    )

    strong = {
        "candidate_id": "strong",
        "hardware": 100,
        "startup": 1.0,
        "survival_log10": -0.1,
    }
    weak = {
        "candidate_id": "weak",
        "hardware": 120,
        "startup": 1.0,
        "survival_log10": -1.0,
    }

    assert dominates(strong, weak, objectives)
    assert not dominates(weak, strong, objectives)



def test_log_space_objective_keeps_small_absolute_improvements_at_large_magnitude():
    objectives = (
        Objective("hardware", "min"),
        Objective("startup", "min"),
        Objective("survival_log10", "max"),
    )

    better = {
        "candidate_id": "better",
        "hardware": 100,
        "startup": 1.0,
        "survival_log10": -70000.000000,
    }
    worse = {
        "candidate_id": "worse",
        "hardware": 100,
        "startup": 1.0,
        "survival_log10": -70000.000001,
    }

    assert dominates(better, worse, objectives)

def test_batch_quantization_creates_genuinely_dominated_prefill_policies(
    policy_result: dict[str, object],
):
    candidates = {
        row["candidate_id"]: row
        for row in policy_result["feasible_candidates"]
    }

    # 12-state buffer: every non-zero fraction needs one successful 12-state
    # prefill batch. Full prefill therefore has the same startup cost but lower
    # starvation risk than 25/50/75%.
    assert candidates["B012_F025"]["is_pareto"] is False
    assert "B012_F100" in candidates["B012_F025"]["dominated_by"]
    assert candidates["B012_F050"]["is_pareto"] is False
    assert "B012_F100" in candidates["B012_F050"]["dominated_by"]
    assert candidates["B012_F075"]["is_pareto"] is False
    assert "B012_F100" in candidates["B012_F075"]["dominated_by"]

    # 24-state buffer has the same effect in two batch-quantized pairs.
    assert candidates["B024_F025"]["is_pareto"] is False
    assert "B024_F050" in candidates["B024_F025"]["dominated_by"]
    assert candidates["B024_F075"]["is_pareto"] is False
    assert "B024_F100" in candidates["B024_F075"]["dominated_by"]


def test_policy_search_reference_views_are_constraint_driven(
    policy_result: dict[str, object],
):
    views = policy_result["risk_target_views"]

    assert policy_result["candidate_count"] == 20
    assert policy_result["feasible_candidate_count"] == 20
    assert policy_result["pareto_candidate_count"] < 20

    assert views["0.1"]["candidate_id"] == "B096_F025"
    assert views["0.01"]["candidate_id"] == "B096_F025"
    assert views["0.001"]["candidate_id"] == "B096_F050"
    assert views["0.0001"]["candidate_id"] == "B096_F050"
    assert views["1e-05"] is None


def test_50_percent_96_state_policy_is_pareto(
    policy_result: dict[str, object],
):
    frontier_ids = {
        row["candidate_id"]
        for row in policy_result["pareto_frontier"]
    }
    assert "B096_F050" in frontier_ids


def test_policy_search_writes_machine_readable_outputs(
    tmp_path: Path,
    policy_result: dict[str, object],
):
    paths = write_outputs(policy_result, output_dir=tmp_path)

    for path in paths.values():
        file_path = Path(path)
        assert file_path.exists()
        assert file_path.stat().st_size > 0


def test_policy_pareto_visualization_writes_two_pngs(
    tmp_path: Path,
    policy_result: dict[str, object],
):
    paths = render_policy_pareto_plots(
        policy_result,
        output_dir=tmp_path,
    )

    assert set(paths) == {"qubits_vs_risk", "prefill_vs_risk"}
    for path in paths.values():
        file_path = Path(path)
        assert file_path.exists()
        assert file_path.suffix == ".png"
        assert file_path.stat().st_size > 1000


def test_pareto_partition_rejects_no_objectives():
    with pytest.raises(ParetoError):
        pareto_partition([{"candidate_id": "x", "value": 1}], [])
