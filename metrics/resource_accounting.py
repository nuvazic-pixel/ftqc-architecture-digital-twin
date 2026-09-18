from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ResourceTerm:
    """One auditable contribution to the machine resource account."""

    name: str
    value: int | None
    source: str
    model: str
    confidence: str
    required: bool = True
    notes: str | None = None

    @property
    def complete(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class ResourceAccountingResult:
    """Aggregate resource account that never maps missing terms to zero."""

    terms: tuple[ResourceTerm, ...]
    known_subtotal: int
    total_physical_qubits: int | None
    complete: bool
    missing_terms: tuple[str, ...]


def aggregate_resource_terms(
    terms: Iterable[ResourceTerm],
) -> ResourceAccountingResult:
    items = tuple(terms)

    known_subtotal = sum(term.value for term in items if term.value is not None)
    missing = tuple(
        term.name for term in items if term.required and term.value is None
    )
    complete = len(missing) == 0

    return ResourceAccountingResult(
        terms=items,
        known_subtotal=known_subtotal,
        total_physical_qubits=known_subtotal if complete else None,
        complete=complete,
        missing_terms=missing,
    )
