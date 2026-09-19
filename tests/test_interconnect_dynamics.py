from __future__ import annotations

from pathlib import Path

import pytest

from experiments.multi_factory_pareto_search import run as run_floorplan
from experiments.transport_aware_pareto_search import (
    run,
    write_outputs,
)
from simulator.floorplanner import build_greedy_floorplan
from simulator.interconnect_dynamics import (
    analyze_transport_aware_starvation,
    factory_paths_from_floorplan,
    schedule_successful_batches,
)


@pytest.fixture(scope="module")
def transport_result() -> dict[str, object]:
    return run(
        "configs/litinski_multi_factory_transport_pareto_10mT.yaml"
    )


def test_pipelined_single_path_latency_is_path_plus_batch_minus_one():
    paths = {1: ((0, 0), (1, 0), (2, 0))}
    schedule = schedule_successful_batches(
        factory_paths=paths,
        successful_factories=(1,),
        output_states_per_batch=12,
        lane_capacity_states_per_logical_step=1,
    )

    assert schedule.completion_steps[1] == 14


def test_shared_single_cell_serializes_two_simultaneous_batches_fairly():
    paths = {
        1: ((0, 0),),
        2: ((0, 0),),
    }
    schedule = schedule_successful_batches(
        factory_paths=paths,
        successful_factories=(1, 2),
        output_states_per_batch=12,
        lane_capacity_states_per_logical_step=1,
    )

    assert schedule.completion_steps[1] == 23
    assert schedule.completion_steps[2] == 24


def test_transport_risk_is_not_better_than_zero_latency_floorplan_for_same_policy():
    floorplan_result = run_floorplan(
        "configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml"
    )
    floorplan_candidates = {
        row["candidate_id"]: row
        for row in floorplan_result["feasible_candidates"]
    }

    transport = run(
        "configs/litinski_multi_factory_transport_pareto_10mT.yaml"
    )
    transport_candidates = {
        row["candidate_id"]: row
        for row in transport["feasible_candidates"]
    }

    candidate_id = "N2_B048_STAG_I012"
    assert transport_candidates[candidate_id][
        "probability_any_starvation"
    ] >= floorplan_candidates[candidate_id][
        "probability_any_starvation"
    ]


def test_transport_kernel_reports_nonzero_latency_and_stall_reward():
    floorplan = build_greedy_floorplan(
        factory_count=2,
        data_block_tiles=153,
        shared_buffer_tiles=52,
        factory_tiles=44,
        clearance_tiles=1,
        search_margin_tiles=24,
    )

    result = analyze_transport_aware_starvation(
        floorplan=floorplan,
        target_states=10_000_000,
        nominal_runtime_ns=3_600_000_000_000,
        batch_duration_ns=99 * 27 * 1000,
        factories=2,
        phase_policy="even_staggered",
        output_states_per_batch=12,
        batch_success_probability=0.89,
        capacity_states=48,
        initial_buffer_states=12,
        logical_step_ns=27_000,
        lane_capacity_states_per_logical_step=1,
    )

    assert result.max_single_batch_transport_latency_ns > 0
    assert result.probability_any_starvation > 0
    assert result.expected_starved_service_slots >= 0
    assert result.expected_stall_extension_seconds >= 0


def test_floorplan_factory_paths_are_explicit_and_complete():
    floorplan = build_greedy_floorplan(
        factory_count=3,
        data_block_tiles=153,
        shared_buffer_tiles=52,
        factory_tiles=44,
        clearance_tiles=1,
        search_margin_tiles=24,
    )
    paths = factory_paths_from_floorplan(floorplan)

    assert set(paths) == {1, 2, 3}
    assert all(len(path) >= 1 for path in paths.values())


def test_transport_aware_search_exposes_reference_map_for_review(
    transport_result: dict[str, object],
):
    assert transport_result["candidate_count"] == 42
    assert transport_result["feasible_candidate_count"] > 0
    assert transport_result["pareto_candidate_count"] > 0

    # Deliberate temporary discovery assertion. Replace with locked regression
    # values after CI exposes the exact transport-aware reference map.
    assert transport_result["risk_target_views"] == {}, (
        transport_result["risk_target_views"],
        transport_result["infeasible_candidates"],
    )


def test_transport_aware_outputs_are_machine_readable(
    tmp_path: Path,
    transport_result: dict[str, object],
):
    paths = write_outputs(transport_result, output_dir=tmp_path)

    for path in paths.values():
        output = Path(path)
        assert output.exists()
        assert output.stat().st_size > 0
