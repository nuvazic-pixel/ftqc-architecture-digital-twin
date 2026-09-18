# FTQC Architecture Digital Twin

A reproducible simulator for fault-tolerant quantum-computing (FTQC) architecture co-design.

## v0.1 goal

Build a deterministic baseline pipeline:

```text
baseline.yaml
  -> config loader
  -> surface-code model
  -> regression tests
```

The first invariant is the baseline code distance:

```text
p_2q = 1e-3
p_th = 1e-2
A = 0.1
p_L,target = 1e-12
=> d = 21
```

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

Every benchmark parameter is stored in configuration with explicit provenance labels such as `benchmark_assumption`, `model_assumption`, or `model_derived`.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest
```
