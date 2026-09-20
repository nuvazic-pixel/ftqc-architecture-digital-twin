from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
from typing import Iterable


class M17CandidateError(ValueError):
    """Raised when M17 candidate-generation inputs are invalid."""


@dataclass(frozen=True)
class LayoutCandidateSpec:
    candidate_id: str
    factory_count: int
    corridor_sharing_degree: float
    topology_class: str
    placement_radius_tiles: int
    clearance_tiles: int
    shared_trunk_bias: float
    route_overlap_target_fraction: float
    anchor_rotation_index: int
    generator_version: str = "m17_candidate_generator_v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BeamSearchConfig:
    beam_width: int
    sharing_degrees: tuple[float, ...]
    variants_per_degree: int
    min_placement_radius_tiles: int
    max_placement_radius_tiles: int
    clearance_tiles: int
    generator_version: str = "m17_candidate_generator_v1"


def _validate_sharing_degree(value: float) -> float:
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise M17CandidateError(
            "corridor_sharing_degree must be in [0, 1]."
        )
    return value


def topology_class_for_sharing(degree: float) -> str:
    degree = _validate_sharing_degree(degree)
    if degree <= 0.10:
        return "isolated"
    if degree < 0.40:
        return "low_share"
    if degree < 0.70:
        return "balanced"
    if degree < 0.90:
        return "high_share"
    return "shared_trunk"


def _placement_radius(
    *,
    degree: float,
    minimum: int,
    maximum: int,
) -> int:
    if minimum <= 0:
        raise M17CandidateError(
            "min_placement_radius_tiles must be > 0."
        )
    if maximum < minimum:
        raise M17CandidateError(
            "max_placement_radius_tiles must be >= minimum."
        )

    # More corridor sharing deliberately biases the generator toward compact
    # placements around the shared-buffer region.
    radius = maximum - degree * (maximum - minimum)
    return int(round(radius))


def _candidate_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:10]
    factories = int(payload["factory_count"])
    sharing = int(round(float(payload["corridor_sharing_degree"]) * 100))
    variant = int(payload["anchor_rotation_index"])
    return f"M17_N{factories}_S{sharing:03d}_V{variant:02d}_{digest}"


def generate_layout_candidate_specs(
    *,
    factory_count: int,
    config: BeamSearchConfig,
) -> tuple[LayoutCandidateSpec, ...]:
    """
    Generate deterministic M17 topology intents spanning isolated to shared.

    This is deliberately a *candidate-spec generator*, not yet the expensive
    placement/routing evaluator. Each spec controls two levers that the M17
    beam engine will materialize:

      - placement radius: compactness around the shared buffer;
      - corridor-sharing bias: preference for reusing existing route cells.

    The output intentionally contains endpoints near 0 and 1 sharing so the
    downstream beam search cannot silently collapse onto only one topology type.
    """
    if factory_count <= 0:
        raise M17CandidateError("factory_count must be > 0.")
    if config.beam_width <= 0:
        raise M17CandidateError("beam_width must be > 0.")
    if config.variants_per_degree <= 0:
        raise M17CandidateError(
            "variants_per_degree must be > 0."
        )
    if config.clearance_tiles < 0:
        raise M17CandidateError("clearance_tiles must be >= 0.")
    if not config.sharing_degrees:
        raise M17CandidateError(
            "sharing_degrees must contain at least one value."
        )

    degrees = tuple(
        sorted({_validate_sharing_degree(x) for x in config.sharing_degrees})
    )

    candidates: list[LayoutCandidateSpec] = []
    for degree in degrees:
        radius = _placement_radius(
            degree=degree,
            minimum=config.min_placement_radius_tiles,
            maximum=config.max_placement_radius_tiles,
        )
        topology_class = topology_class_for_sharing(degree)

        for rotation_index in range(config.variants_per_degree):
            payload = {
                "factory_count": factory_count,
                "corridor_sharing_degree": degree,
                "topology_class": topology_class,
                "placement_radius_tiles": radius,
                "clearance_tiles": config.clearance_tiles,
                "shared_trunk_bias": degree,
                "route_overlap_target_fraction": degree,
                "anchor_rotation_index": rotation_index,
                "generator_version": config.generator_version,
            }
            candidate_id = _candidate_id(payload)
            candidates.append(
                LayoutCandidateSpec(
                    candidate_id=candidate_id,
                    factory_count=factory_count,
                    corridor_sharing_degree=degree,
                    topology_class=topology_class,
                    placement_radius_tiles=radius,
                    clearance_tiles=config.clearance_tiles,
                    shared_trunk_bias=degree,
                    route_overlap_target_fraction=degree,
                    anchor_rotation_index=rotation_index,
                    generator_version=config.generator_version,
                )
            )

    # Candidate generation is broader than the beam width by design. The beam
    # width governs how many partial layouts survive each materialization step,
    # while the spec generator preserves topology diversity.
    return tuple(candidates)


def diversity_summary(
    candidates: Iterable[LayoutCandidateSpec],
) -> dict[str, object]:
    items = tuple(candidates)
    if not items:
        raise M17CandidateError(
            "cannot summarize an empty candidate set."
        )

    degrees = sorted(
        {candidate.corridor_sharing_degree for candidate in items}
    )
    classes = sorted(
        {candidate.topology_class for candidate in items}
    )

    return {
        "candidate_count": len(items),
        "factory_counts": sorted(
            {candidate.factory_count for candidate in items}
        ),
        "sharing_degrees": degrees,
        "topology_classes": classes,
        "min_sharing_degree": min(degrees),
        "max_sharing_degree": max(degrees),
        "contains_isolated_endpoint": min(degrees) <= 0.10,
        "contains_shared_trunk_endpoint": max(degrees) >= 0.90,
    }


def cheap_beam_order_key(
    candidate: LayoutCandidateSpec,
) -> tuple[float, int, int, str]:
    """
    Deterministic cheap ordering used only before M16 evaluation exists.

    It is intentionally NOT a final scalar architecture score. The full M17
    engine will replace this with Pareto-preserving spatial/temporal evaluation.
    """
    center_distance = abs(candidate.corridor_sharing_degree - 0.5)
    return (
        center_distance,
        candidate.placement_radius_tiles,
        candidate.anchor_rotation_index,
        candidate.candidate_id,
    )
