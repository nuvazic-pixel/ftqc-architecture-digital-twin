# FTQC Architecture Digital Twin

A reproducible simulator for fault-tolerant quantum-computing (FTQC) architecture co-design.

## Historical regression baseline

The original regression fixture remains frozen and reproducible:

```text
p_2q = 1e-3
p_th = 1e-2
A = 0.1
p_L,target = 1e-12
=> d = 21

legacy r_T(21) = 60.47 states/s/factory
legacy zeta = 3
T_count = 10,000,000
T_wall,target = 3600 s
=> legacy N_fac,min = 138
```

These values remain regression fixtures and are not silently rewritten by later
protocol-specific models.

## Protocol-consistent Litinski benchmark

Milestone 5 adds a separate named benchmark instead of mutating the historical
baseline:

```text
configs/litinski_minimal_10mT.yaml
```

The benchmark adapts the minimal p=1e-3 setup from Daniel Litinski,
*A Game of Surface Codes* (Quantum 3, 128, 2019) to the repository's
10,000,000-T-state workload.

Named layout and protocol inputs:

```text
compact data block       153 tiles
116-to-12 distillation    44 tiles
output storage            13 tiles
total                    210 tiles

batch outputs              12 states
batch duration             99 logical time steps
batch success              0.89
code-cycle benchmark        1 microsecond
```

The protocol-derived expected production interval is

```text
99 / (12 * 0.89) ~= 9.26966 logical time steps / usable state
```

and one logical time step is modeled as `d` code cycles.

### Whole-computation reliability

This benchmark does not select distance from the old per-cycle target alone.
It applies the tile/time reliability budget used by the named architecture:

```text
N_tiles * N_time_steps * d * p_L(p,d) <= 0.01
```

For T_count=10,000,000 and p=1e-3:

```text
d = 23 -> estimated logical-failure budget ~= 0.04477  (fails)
d = 25 -> estimated logical-failure budget ~= 0.00487  (passes)
```

Therefore the protocol-consistent benchmark selects `d=25`.

### First protocol-consistent result

At `d=25` with a 1 microsecond code cycle:

```text
factory throughput       ~= 4,315.15 usable states/s
factories                = 1
runtime                  ~= 2,317.42 s  (38.62 min)
physical qubits          = 262,500
STV                      ~= 6.08321629e8 physical-qubit*s
failure-budget estimate  ~= 0.0048666
```

Unlike the historical mixed-model fixture, geometry, batch timing, batch
success probability, code-distance selection, runtime, and footprint now come
from one named architecture model plus one explicit hardware timing assumption.

The 1 microsecond code-cycle value is a benchmark assumption used in Litinski's
worked example, not a universal hardware constant.

## Scientific guardrails

- The historical baseline remains immutable for regression.
- Protocol-derived throughput does not use the legacy scalar routing penalty.
- Routing/workspace are not separately added for the named minimal layout;
  their required geometry is treated as embedded in the cited tile layout.
- Expected batch success is used as an average-rate model; stochastic burst
  simulation is a later milestone.
- The whole-computation failure expression is a resource-estimation budget
  model, not an exact stochastic failure probability.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest
python -m experiments.static_resources --config configs/baseline.yaml
python -m experiments.whole_machine_accounting --config configs/baseline.yaml
python -m experiments.litinski_minimal_setup --config configs/litinski_minimal_10mT.yaml
```

## Milestones

- [x] Config schema and historical regression baseline
- [x] Surface-code distance and floating-point boundary tests
- [x] Legacy factory regression fixture
- [x] Lower-bound resource metrics
- [x] Provenance-aware partial whole-machine accounting
- [ ] Protocol-consistent factory timing, reliability, footprint, and STV
- [ ] Stochastic/burst-aware magic-state production
- [ ] Multi-factory space-time trade-off search
- [ ] Static Pareto search
