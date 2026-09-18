from metrics.resource_accounting import ResourceTerm


def unmodeled_routing_term() -> ResourceTerm:
    """Return an explicit missing routing term rather than silently using zero."""
    return ResourceTerm(
        name="routing_qubits",
        value=None,
        source="unmodeled",
        model="unmodeled",
        confidence="unknown",
        notes="Topology-derived routing ancillas are not yet modeled.",
    )
