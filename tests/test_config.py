from simulator.config import load_config


def test_load_baseline_config():
    config = load_config("configs/baseline.yaml")

    assert config["experiment"]["name"] == "baseline_transmon_v01"
    assert config["qec"]["physical_error_threshold"]["value"] == 1.0e-2
    assert config["hardware"]["errors"]["p_2q"]["value"] == 1.0e-3
