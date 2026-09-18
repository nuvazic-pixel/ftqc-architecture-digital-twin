from simulator.config import load_config
from simulator.factory import factory_rate, minimum_factories
from simulator.surface_code import required_code_distance


def test_factory_rate_d21_is_regression_fixture():
    config = load_config("configs/baseline.yaml")

    assert factory_rate(distance=21, config=config) == 60.47


def test_baseline_minimum_factory_count_is_138():
    config = load_config("configs/baseline.yaml")

    d = required_code_distance(
        physical_error=config["hardware"]["errors"]["p_2q"]["value"],
        physical_error_threshold=config["qec"]["physical_error_threshold"]["value"],
        fit_A=config["qec"]["fit_A"]["value"],
        target_logical_error=config["qec"]["target_logical_error"],
        allowed_distances=config["qec"]["allowed_distances"],
    )

    n_fac = minimum_factories(
        distance=d,
        t_count=config["workload"]["t_count"],
        wall_time_seconds=config["optimizer"]["constraints"]["max_runtime_seconds"],
        routing_factor=config["hardware"]["topology"]["zeta"],
        config=config,
    )

    assert d == 21
    assert n_fac == 138
