# FTQC Architecture Digital Twin

A reproducible simulator for fault-tolerant quantum-computing (FTQC) architecture co-design.

## Current baseline

The current regression baseline retains:

```text
p_2q = 1e-3
p_th = 1e-2
A = 0.1
p_L,target = 1e-12
=> d = 21

r_T(21) = 60.47 states/s/factory
zeta = 3
T_count = 10,000,000
T_wall,target = 3600 s
=> N_fac,min = 138
```

## Milestone 4: provenance-aware whole-machine accounting

The resource account now distinguishes between known terms and genuinely
unmodeled terms. Missing required terms are **never converted to zero**.

For the p=1e-3 baseline, the factory geometry is anchored to the compact
116-to-12 layout described by Daniel Litinski in *A Game of Surface Codes:
Large-Scale Quantum Computing with Lattice Surgery*, Quantum 3, 128 (2019).

That layout uses 44 distillation tiles and, in the cited minimal setup,
13 output-storage tiles. A surface-code tile is modeled with the common
approximately `2 d^2` physical-qubit scaling.

At d=21:

```text
data-block lower bound       88,200
138 x factory distillation 5,355,504
138 x output storage       1,582,308
------------------------------------
known subtotal             7,026,012 physical qubits
```

Routing ancillas and lattice-surgery workspace remain explicitly
`unmodeled`, therefore:

```text
total_physical_qubits = incomplete
accounting_complete   = false
```

This is intentional. The simulator reports a known subtotal rather than
misrepresenting missing architecture costs as zero.

### Important protocol-consistency guardrail

The current `r_T(d)` throughput values are regression fixtures marked
`model_derived`. They have **not yet been derived from the Litinski
116-to-12 timing model**. Consequently, Milestone 4 labels the throughput
binding as `unverified`.

The known-subtotal STV is useful for regression and sensitivity analysis,
but it is not yet a publication-ready whole-machine STV until geometry,
timing, routing, and factory protocol are made mutually consistent.

## Research direction

The longer-term goal is an adaptive digital twin that co-optimizes:

- code distance
- magic-state factory provisioning
- topology-aware routing
- physical-qubit footprint
- runtime
- space-time volume

under a fixed logical reliability constraint.

## Reproducibility

Every benchmark parameter is stored in configuration with explicit provenance.
Resource terms carry source, model, confidence, and notes. Missing required
terms make the aggregate result incomplete instead of silently contributing
zero.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest
python -m experiments.static_resources --config configs/baseline.yaml
python -m experiments.whole_machine_accounting --config configs/baseline.yaml
```

## Milestones

- [x] Config schema and provenance-aware baseline
- [x] Surface-code distance model and d=21 regression test
- [x] Factory throughput regression fixture and N_fac,min=138
- [x] Lower-bound data footprint, supply-limited runtime, and STV
- [ ] Provenance-aware whole-machine accounting
- [ ] Protocol-consistent factory throughput and footprint model
- [ ] Topology-derived routing/workspace model
- [ ] Static Pareto search
