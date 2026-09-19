from __future__ import annotations

from pathlib import Path

import pytest

from experiments.inflight_network_stress import run, write_outputs
from simulator.inflight_network import PersistentReservationNetwork


@pytest.fixture(scope="module")
def stress_result() -> dict[str, object]:
    return run("configs/litinski_inflight_network_stress.yaml")


def test_later_batch_sees_persistent_reservations_from_earlier_event():
    network = PersistentReservationNetwork(
        factory_paths={
            1: ((0, 0),),
            2: ((0, 0),),
        },
        lane_capacity_states_per_tick=1,
        hop_latency_ticks=2,
    )

    first = network.enqueue_simultaneous_batches(
        generation_tick=0,
        batches=(("A", 1, 2),),
    )[0]

    second = network.enqueue_simultaneous_batches(
        generation_tick=1,
        batches=(("B", 2, 2),),
    )[0]

    assert first.completion_tick == 4
    assert second.completion_tick == 8
    assert len(network.inflight_batches_at(2)) == 2
    assert len(network.completed_batches_by(4)) == 1


def test_simultaneous_batches_are_round_robin_fair_on_shared_cell():
    network = PersistentReservationNetwork(
        factory_paths={
            1: ((0, 0),),
            2: ((0, 0),),
        },
        lane_capacity_states_per_tick=1,
        hop_latency_ticks=1,
    )

    records = network.enqueue_simultaneous_batches(
        generation_tick=0,
        batches=(
            ("A", 1, 2),
            ("B", 2, 2),
        ),
    )
    by_factory = {record.factory_id: record for record in records}

    assert by_factory[1].completion_tick == 3
    assert by_factory[2].completion_tick == 4


def test_persistent_network_summary_detects_cross_event_inflight_state():
    network = PersistentReservationNetwork(
        factory_paths={1: ((0, 0), (1, 0))},
        lane_capacity_states_per_tick=1,
        hop_latency_ticks=3,
    )

    event_ticks = [0, 4, 8]
    for index, tick in enumerate(event_ticks):
        network.enqueue_simultaneous_batches(
            generation_tick=tick,
            batches=((f"B{index}", 1, 2),),
        )

    summary = network.summarize(
        event_ticks=event_ticks,
        generation_horizon_end_tick=12,
    )

    assert summary.max_inflight_batches_at_event_boundary >= 1
    assert summary.event_boundaries_with_inflight >= 1
    assert summary.max_batch_latency_ticks > 4


def test_real_floorplan_stress_shows_latency_sensitivity(
    stress_result: dict[str, object],
):
    rows = {
        (row["scenario"], row["hop_latency_logical_steps"]): row
        for row in stress_result["results"]
    }

    assert stress_result["row_count"] == 9

    for scenario in ("N2_B048_STAG", "N3_B048_STAG", "N4_B096_STAG"):
        fast = rows[(scenario, 1)]
        slow = rows[(scenario, 4)]

        assert slow["mean_batch_latency_logical_steps"] > fast[
            "mean_batch_latency_logical_steps"
        ]
        assert slow[
            "fraction_event_boundaries_with_inflight"
        ] >= fast["fraction_event_boundaries_with_inflight"]
        assert slow[
            "max_contention_wait_logical_steps_per_state"
        ] >= fast[
            "max_contention_wait_logical_steps_per_state"
        ]


def test_stress_outputs_are_machine_readable(
    tmp_path: Path,
    stress_result: dict[str, object],
):
    paths = write_outputs(stress_result, output_dir=tmp_path)

    assert set(paths) == {"json", "csv"}
    for path in paths.values():
        output = Path(path)
        assert output.exists()
        assert output.stat().st_size > 0


def test_discover_persistent_network_stress_profile(
    stress_result: dict[str, object],
):
    # Temporary discovery assertion; replace with locked regression values.
    assert False, stress_result["results"]
