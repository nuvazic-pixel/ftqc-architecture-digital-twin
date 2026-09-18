from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the configuration format is invalid."""


def _require_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping.")
    return value


def load_config(path: str | Path) -> dict[str, Any]:
    """
    Load and structurally validate a simulator YAML configuration.

    Important:
    This function validates file shape and basic types only.
    Physics/domain validation belongs in the relevant simulation model.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(config_path)

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ConfigError("Top-level YAML document must be a mapping.")

    for section in ("experiment", "workload", "hardware", "qec", "factories", "optimizer", "outputs"):
        _require_mapping(data, section)

    hardware = data["hardware"]
    errors = _require_mapping(hardware, "errors")
    qec = data["qec"]

    for parameter in ("p_1q", "p_2q", "p_measurement"):
        entry = _require_mapping(errors, parameter)
        if not isinstance(entry.get("value"), (int, float)):
            raise ConfigError(f"hardware.errors.{parameter}.value must be numeric.")
        if not isinstance(entry.get("source"), str):
            raise ConfigError(f"hardware.errors.{parameter}.source must be a string.")

    for parameter in ("physical_error_threshold", "fit_A"):
        entry = _require_mapping(qec, parameter)
        if not isinstance(entry.get("value"), (int, float)):
            raise ConfigError(f"qec.{parameter}.value must be numeric.")
        if not isinstance(entry.get("source"), str):
            raise ConfigError(f"qec.{parameter}.source must be a string.")

    target = qec.get("target_logical_error")
    if not isinstance(target, (int, float)):
        raise ConfigError("qec.target_logical_error must be numeric.")

    distances = qec.get("allowed_distances")
    if not isinstance(distances, list) or not all(isinstance(d, int) for d in distances):
        raise ConfigError("qec.allowed_distances must be a list of integers.")

    return data
