from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Literal, Mapping, Sequence


Direction = Literal["min", "max"]


class ParetoError(ValueError):
    """Raised when Pareto-search inputs are invalid."""


@dataclass(frozen=True)
class Objective:
    metric: str
    direction: Direction
    rel_tol: float = 1e-12
    abs_tol: float = 1e-15

    def __post_init__(self) -> None:
        if not self.metric:
            raise ParetoError("objective metric must be non-empty.")
        if self.direction not in ("min", "max"):
            raise ParetoError("objective direction must be 'min' or 'max'.")
        if self.rel_tol < 0 or self.abs_tol < 0:
            raise ParetoError("objective tolerances must be >= 0.")


def _value(row: Mapping[str, object], objective: Objective) -> float:
    if objective.metric not in row:
        raise ParetoError(
            f"candidate is missing Pareto metric '{objective.metric}'."
        )
    value = float(row[objective.metric])
    if not math.isfinite(value):
        raise ParetoError(
            f"Pareto metric '{objective.metric}' must be finite; got {value!r}."
        )
    return value


def dominates(
    left: Mapping[str, object],
    right: Mapping[str, object],
    objectives: Sequence[Objective],
) -> bool:
    """
    Return True when left weakly improves every objective and strictly improves
    at least one objective, respecting each metric's direction and tolerance.
    """
    if not objectives:
        raise ParetoError("at least one objective is required.")

    strictly_better = False

    for objective in objectives:
        a = _value(left, objective)
        b = _value(right, objective)

        if math.isclose(
            a,
            b,
            rel_tol=objective.rel_tol,
            abs_tol=objective.abs_tol,
        ):
            continue

        if objective.direction == "min":
            if a > b:
                return False
            strictly_better = True
        else:
            if a < b:
                return False
            strictly_better = True

    return strictly_better


def pareto_partition(
    candidates: Iterable[Mapping[str, object]],
    objectives: Sequence[Objective],
    *,
    id_key: str = "candidate_id",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """
    Partition candidates into Pareto-frontier and dominated sets.

    Each returned row is copied and annotated with:
      - is_pareto
      - dominated_by: candidate IDs that dominate the row
    """
    rows = [dict(candidate) for candidate in candidates]
    if not rows:
        raise ParetoError("at least one candidate is required.")

    for index, row in enumerate(rows):
        row.setdefault(id_key, f"candidate_{index:04d}")

    frontier: list[dict[str, object]] = []
    dominated_rows: list[dict[str, object]] = []

    for index, row in enumerate(rows):
        dominators: list[str] = []

        for other_index, other in enumerate(rows):
            if index == other_index:
                continue
            if dominates(other, row, objectives):
                dominators.append(str(other[id_key]))

        annotated = dict(row)
        annotated["dominated_by"] = sorted(dominators)
        annotated["is_pareto"] = not dominators

        if dominators:
            dominated_rows.append(annotated)
        else:
            frontier.append(annotated)

    return frontier, dominated_rows
