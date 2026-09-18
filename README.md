# FTQC Architecture Digital Twin

A reproducible simulator for fault-tolerant quantum-computing (FTQC) architecture co-design.

## v0.1 goal

Build a deterministic baseline pipeline:

```text
baseline.yaml
  -> config loader
  -> surface-code model
  -> factory model
  -> regression tests
```

The current baseline invariants are:

```text
p_2q = 1e-3
p_th = 1e-2
A = 0.1
p_L,target = 1e-12
=> d = 21

r_T(21) = 60.47 states/s/factory
zeta = 3
T_count = 10,000,000
T_wall = 3600 s
=> N_fac,min = 138
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

Physics/domain validation lives in the corresponding model modules. For example, the YAML loader validates structure and types, while `surface_code.py` rejects configurations at or above the configured physical QEC threshold.

### Repository initialization note

The initial repository bootstrap was written through the GitHub connector and therefore appears as several consecutive commits with the same initialization message. This is a tooling artifact rather than a sequence of distinct scientific revisions. Subsequent milestones use feature branches and pull requests so they can be reviewed and squash-merged into clean logical commits.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest
```

## Milestones

- [x] Config schema and provenance-aware baseline
- [x] Surface-code distance model and `d == 21` regression test
- [ ] Factory model and `r_T(21) == 60.47` regression test
- [ ] Baseline factory provisioning and `N_fac,min == 138` regression test
- [ ] Static resource metrics and Pareto search
