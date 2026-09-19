from __future__ import annotations

from pathlib import Path

import pytest

from experiments.multi_factory_pareto_search import (
    run,
    write_outputs,
)
from experiments.plot_multi_factory_pareto import (
    render_multi_factory_pareto_plots,
)
from simulator.multi_factory import (
    build_multi_factory_risk_kernel,
    expected_parallel_prefill_rounds,
    multi_factory_startup_cost,
)


@pytest.fixture(scope="module")
def multi_factory_result() -> dict[str, object]:
    return run("configs/litinski_multi_factory_pareto_10mT.yaml")


def test_synchronized_parallel_prefill_rounds_for_one_required_success():
    rounds = expected_parallel_prefill_rounds(
        successful_batches_required=1,
        factories=2,
        batch_success_probability=0.89,
    )

    assert rounds == pytest.approx(
        1.0 / (1.0 - 0.11**2),
        rel=1e-12,
    )


def test_even_staggered_startup_keeps_phase_setup_explicit():
    batch_duration_seconds = 99 * 27 * 1e-6
    startup = multi_factory_startup_cost(
        initial_buffer_states=12,
        factories=2,
        phase_policy="even_staggered",
        batch_duration_seconds=batch_duration_seconds,
        output_states_per_successful_batch=12,
        batch_success_probability=0.89,
    )

    assert startup.phase_setup_seconds == pytest.approx(
        batch_duration_seconds / 2,
        rel=1e-12,
    )
    assert startup.conservative_startup_seconds > (
        startup.expected_prefill_seconds
    )


def test_phase_staggering_changes_exact_risk_at_same_hardware():
    common = dict(
        target_states=10_000_000,
        nominal_runtime_ns=3_600_000_000_000,
        batch_duration_ns=99 * 27 * 1000,
        factories=2,
        output_states_per_successful_batch=12,
        batch_success_probability=0.89,
        capacity_states=48,
    )

    synchronized = build_multi_factory_risk_kernel(
        phase_policy="synchronized",
        **common,
    ).probability_any_starvation(initial_buffer_states=12)

    staggered = build_multi_factory_risk_kernel(
        phase_policy="even_staggered",
        **common,
    ).probability_any_starvation(initial_buffer_states=12)

    assert synchronized == pytest.approx(
        0.0121455553062,
        rel=1e-8,
    )
    assert staggered == pytest.approx(
        0.00137853573675,
        rel=1e-8,
    )
    assert staggered < synchronized


def test_multi_factory_search_exposes_risk_target_reference_policies(
    multi_factory_result: dict[str, object],
):
    views = multi_factory_result["risk_target_views"]

    assert multi_factory_result["candidate_count"] == 42
    assert multi_factory_result["feasible_candidate_count"] == 42
    assert multi_factory_result["pareto_candidate_count"] < 42

    assert views["0.01"]["candidate_id"] == "N2_B048_STAG_I012"
    assert views["0.0001"]["candidate_id"] == "N2_B048_SYNC_I024"
    assert views["1e-06"]["candidate_id"] == "N3_B048_SYNC_I024"
    assert views["1e-09"]["candidate_id"] == "N3_B048_STAG_I024"
    assert views["1e-12"]["candidate_id"] == "N2_B096_STAG_I048"
    assert views["1e-18"]["candidate_id"] == "N3_B096_STAG_I048"
    assert views["1e-24"]["candidate_id"] == "N4_B096_STAG_I048"


def test_multi_factory_counts_and_layout_assumption_remain_explicit(
    multi_factory_result: dict[str, object],
):
    assert (
        multi_factory_result["layout_model"]
        == "shared_buffer_replaces_per_factory_output_storage"
    )
    assert (
        multi_factory_result["routing_interconnect_status"]
        == "unmodeled"
    )

    candidates = {
        row["candidate_id"]: row
        for row in multi_factory_result["feasible_candidates"]
    }
    assert candidates["N2_B048_SYNC_I012"]["physical_qubits"] == 427_194
    assert candidates["N3_B048_SYNC_I024"]["physical_qubits"] == 491_346
    assert candidates["N4_B096_STAG_I048"]["physical_qubits"] == 631_314


def test_multi_factory_outputs_are_machine_readable(
    tmp_path: Path,
    multi_factory_result: dict[str, object],
):
    paths = write_outputs(
        multi_factory_result,
        output_dir=tmp_path,
    )

    for path in paths.values():
        file_path = Path(path)
        assert file_path.exists()
        assert file_path.stat().st_size > 0


def test_multi_factory_pareto_visualization_writes_two_pngs(
    tmp_path: Path,
    multi_factory_result: dict[str, object],
):
    paths = render_multi_factory_pareto_plots(
        multi_factory_result,
        output_dir=tmp_path,
    )

    assert set(paths) == {"qubits_vs_risk", "startup_vs_risk"}
    for path in paths.values():
        file_path = Path(path)
        assert file_path.exists()
        assert file_path.suffix == ".png"
        assert file_path.stat().st_size > 1000
