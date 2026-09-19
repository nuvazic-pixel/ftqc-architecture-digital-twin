from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.finite_buffer_backpressure_stress import (
    run,
    write_outputs,
)
from simulator.backpressure_network import (
    FiniteBufferBackpressureNetwork,
)


@pytest.fixture(scope="module")
def stress_result() -> dict[str, object]:
    return run(
        "configs/litinski_finite_buffer_backpressure_stress.yaml"
    )


def _synthetic_shared_bottleneck(
    *,
    intermediate_capacity: int,
) -> object:
    network = FiniteBufferBackpressureNetwork(
        factory_paths={
            1: ((0, 0), (1, 0)),
            2: ((0, 1), (1, 0)),
        },
        injection_queue_capacity_states=4,
        intermediate_queue_capacity_states=intermediate_capacity,
        injection_bandwidth_states_per_tick=4,
        hop_latency_ticks=2,
    )

    return network.run(
        event_schedule={
            0: (
                (0, 1),
                (0, 2),
            ),
        },
        generation_horizon_end_tick=20,
        states_per_batch=4,
        max_drain_ticks=100,
    )


def test_finite_queue_backpressure_blocks_completed_upstream_cell():
    small = _synthetic_shared_bottleneck(
        intermediate_capacity=1
    )

    assert small.blocked_after_service_ticks > 0
    assert small.intermediate_queue_full_ticks > 0
    assert small.generated_states == 8
    assert small.delivered_states == 8
    assert small.all_generated_states_delivered


def test_larger_intermediate_queue_never_increases_synthetic_blocking():
    small = _synthetic_shared_bottleneck(
        intermediate_capacity=1
    )
    large = _synthetic_shared_bottleneck(
        intermediate_capacity=4
    )

    assert large.blocked_after_service_ticks <= (
        small.blocked_after_service_ticks
    )
    assert large.intermediate_queue_full_ticks <= (
        small.intermediate_queue_full_ticks
    )
    assert large.all_generated_states_delivered


def test_factory_completion_is_suppressed_instead_of_hidden_in_source_buffer():
    network = FiniteBufferBackpressureNetwork(
        factory_paths={1: ((0, 0),)},
        injection_queue_capacity_states=1,
        intermediate_queue_capacity_states=1,
        injection_bandwidth_states_per_tick=1,
        hop_latency_ticks=20,
    )

    result = network.run(
        event_schedule={
            0: ((0, 1),),
            2: ((1, 1),),
            4: ((2, 1),),
        },
        generation_horizon_end_tick=10,
        states_per_batch=4,
        max_drain_ticks=200,
    )

    assert result.scheduled_factory_events == 3
    assert result.suppressed_factory_events >= 1
    assert result.generated_batches < 3
    assert result.all_generated_states_delivered


def test_real_floorplan_matrix_is_lossless(
    stress_result: dict[str, object],
):
    assert stress_result["row_count"] == 16

    for row in stress_result["results"]:
        assert row["all_generated_states_delivered"] is True
        assert row["delivered_states"] == row["generated_states"]
        assert row["max_intermediate_queue_occupancy"] <= row[
            "intermediate_queue_capacity_states"
        ]


def test_outputs_are_machine_readable(
    tmp_path: Path,
    stress_result: dict[str, object],
):
    paths = write_outputs(
        stress_result,
        output_dir=tmp_path,
    )

    assert set(paths) == {"json", "csv"}
    for path in paths.values():
        output = Path(path)
        assert output.exists()
        assert output.stat().st_size > 0


def test_discover_finite_buffer_backpressure_profile(
    stress_result: dict[str, object],
):
    profile = [
        {
            key: row[key]
            for key in (
                "scenario",
                "intermediate_queue_capacity_states",
                "shared_route_cells",
                "suppressed_factory_events",
                "generated_batch_fraction",
                "blocked_after_service_ticks",
                "intermediate_queue_full_ticks",
                "factory_output_backpressure_ticks",
                "max_network_states",
                "max_carryover_batches_at_event_boundary",
                "fraction_event_boundaries_with_carryover",
                "mean_batch_latency_logical_steps",
                "max_batch_latency_logical_steps",
                "drain_tail_logical_steps",
                "busiest_cell_utilization_during_generation_horizon",
            )
        }
        for row in stress_result["results"]
    ]

    raise AssertionError(
        json.dumps(profile, indent=2, sort_keys=True)
    )
