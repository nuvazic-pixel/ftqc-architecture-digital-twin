import pytest

from experiments.prefill_policy_sensitivity import run
from simulator.prefill_policy import prefill_cost, requested_initial_states


def test_fractional_prefill_maps_to_exact_integer_states():
    assert requested_initial_states(
        buffer_capacity_states=96,
        fill_fraction=0.25,
    ) == 24
    assert requested_initial_states(
        buffer_capacity_states=48,
        fill_fraction=0.75,
    ) == 36


def test_prefill_cost_is_protocol_batch_quantized():
    cost = prefill_cost(
        requested_states=3,
        output_states_per_successful_batch=12,
        batch_success_probability=0.89,
        batch_duration_seconds=0.002475,
    )

    assert cost.successful_batches_required == 1
    assert cost.produced_states_on_required_successes == 12
    assert cost.discarded_states_from_final_prefill_batch == 9
    assert cost.expected_prefill_seconds == pytest.approx(
        0.0027808988764044945,
        rel=1e-12,
    )


def test_prefill_policy_exposes_structural_capacity_limit_at_48_states():
    result = run("configs/litinski_prefill_policy_10mT.yaml")
    rows = result["results"]

    cap48 = {
        row["fill_fraction"]: row
        for row in rows
        if row["buffer_capacity_states"] == 48
    }

    assert cap48[0.0]["probability_any_starvation"] == pytest.approx(
        0.929631298851895,
        abs=1e-12,
    )
    assert cap48[1.0]["probability_any_starvation"] == pytest.approx(
        0.9096307972113646,
        abs=1e-10,
    )
    assert cap48[1.0]["probability_any_starvation"] > 0.90


def test_96_state_prefill_dramatically_reduces_exact_starvation_risk():
    result = run("configs/litinski_prefill_policy_10mT.yaml")
    rows = result["results"]

    cap96 = {
        row["fill_fraction"]: row
        for row in rows
        if row["buffer_capacity_states"] == 96
    }

    assert cap96[0.0]["probability_any_starvation"] == pytest.approx(
        0.23974761879314357,
        abs=1e-12,
    )
    assert cap96[0.25]["probability_any_starvation"] == pytest.approx(
        0.001062117561558175,
        abs=1e-12,
    )
    assert cap96[0.50]["probability_any_starvation"] == pytest.approx(
        5.302191344095938e-05,
        abs=1e-15,
    )
    assert cap96[1.0]["probability_any_starvation"] == pytest.approx(
        5.11438798886127e-05,
        abs=1e-15,
    )

    assert cap96[0.25]["expected_prefill_seconds"] == pytest.approx(
        0.0060067415730337085,
        rel=1e-12,
    )
    assert cap96[0.50]["expected_prefill_seconds"] == pytest.approx(
        0.012013483146067417,
        rel=1e-12,
    )
    assert cap96[1.0]["expected_prefill_seconds"] == pytest.approx(
        0.024026966292134834,
        rel=1e-12,
    )


def test_prefill_failure_increment_remains_explicit_and_below_budget():
    result = run("configs/litinski_prefill_policy_10mT.yaml")

    full_96 = next(
        row
        for row in result["results"]
        if row["buffer_capacity_states"] == 96
        and row["fill_fraction"] == 1.0
    )

    assert full_96["code_distance"] == 27
    assert full_96["physical_qubits"] == 438_858
    assert full_96["expected_prefill_failure_increment"] > 0
    assert full_96["conservative_expected_campaign_failure_budget"] < 0.01
