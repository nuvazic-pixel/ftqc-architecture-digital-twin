from __future__ import annotations

import math


class ProtocolFactoryError(ValueError):
    """Raised when a protocol-derived factory parameter is invalid."""


def expected_time_steps_per_good_state(
    *,
    output_states_per_batch: int,
    protocol_steps_per_batch: float,
    batch_success_probability: float,
) -> float:
    """
    Expected protocol time steps per usable output state.

    For a batch producing n outputs in S time steps with batch success
    probability q, the expected usable output rate is n*q/S states per time
    step, so the inverse is S/(n*q).
    """
    if output_states_per_batch <= 0:
        raise ProtocolFactoryError("output_states_per_batch must be > 0.")
    if protocol_steps_per_batch <= 0:
        raise ProtocolFactoryError("protocol_steps_per_batch must be > 0.")
    if not 0 < batch_success_probability <= 1:
        raise ProtocolFactoryError(
            "batch_success_probability must be in the interval (0, 1]."
        )

    return protocol_steps_per_batch / (
        output_states_per_batch * batch_success_probability
    )


def protocol_factory_throughput(
    *,
    distance: int,
    code_cycle_time_seconds: float,
    output_states_per_batch: int,
    protocol_steps_per_batch: float,
    batch_success_probability: float,
) -> float:
    """
    Expected usable magic-state throughput in states/second.

    In the Litinski tile model, one logical time step corresponds to d surface-
    code cycles. This is an intrinsic production rate; no routing/delivery
    penalty is folded into it.
    """
    if distance < 1 or distance % 2 == 0:
        raise ProtocolFactoryError("distance must be a positive odd integer.")
    if code_cycle_time_seconds <= 0:
        raise ProtocolFactoryError("code_cycle_time_seconds must be > 0.")

    steps_per_state = expected_time_steps_per_good_state(
        output_states_per_batch=output_states_per_batch,
        protocol_steps_per_batch=protocol_steps_per_batch,
        batch_success_probability=batch_success_probability,
    )
    seconds_per_state = steps_per_state * distance * code_cycle_time_seconds
    return 1.0 / seconds_per_state


def protocol_runtime_seconds(
    *,
    t_count: int,
    factories: int,
    states_per_second_per_factory: float,
) -> float:
    if t_count < 0:
        raise ProtocolFactoryError("t_count must be >= 0.")
    if factories <= 0:
        raise ProtocolFactoryError("factories must be > 0.")
    if states_per_second_per_factory <= 0:
        raise ProtocolFactoryError(
            "states_per_second_per_factory must be > 0."
        )

    return t_count / (factories * states_per_second_per_factory)


def minimum_protocol_factories(
    *,
    t_count: int,
    max_runtime_seconds: float,
    states_per_second_per_factory: float,
) -> int:
    if t_count < 0:
        raise ProtocolFactoryError("t_count must be >= 0.")
    if max_runtime_seconds <= 0:
        raise ProtocolFactoryError("max_runtime_seconds must be > 0.")
    if states_per_second_per_factory <= 0:
        raise ProtocolFactoryError(
            "states_per_second_per_factory must be > 0."
        )
    if t_count == 0:
        return 0

    demand = t_count / max_runtime_seconds
    return math.ceil(demand / states_per_second_per_factory)
