from __future__ import annotations

from metrics.resource_accounting import (
    ResourceAccountingResult,
    ResourceTerm,
    aggregate_resource_terms,
)


def total_physical_qubits(
    *,
    data_block: ResourceTerm,
    factory_distillation: ResourceTerm,
    factory_output_buffer: ResourceTerm,
    routing: ResourceTerm,
    workspace: ResourceTerm,
) -> ResourceAccountingResult:
    """
    Aggregate whole-machine terms.

    Missing required terms produce total_physical_qubits=None, never zero.
    """
    return aggregate_resource_terms(
        (
            data_block,
            factory_distillation,
            factory_output_buffer,
            routing,
            workspace,
        )
    )
