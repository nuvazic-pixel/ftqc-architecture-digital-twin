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

The named deterministic benchmark is:

```text
configs/litinski_minimal_10mT.yaml
```

For the 10,000,000-T-state workload it selects `d=25` and yields:

```text
factory throughput       ~= 4,315.15 usable states/s
factories                = 1
runtime                  ~= 2,317.42 s
physical qubits          = 262,500
STV                      ~= 6.08321629e8 physical-qubit*s
failure-budget estimate  ~= 0.0048666
```

## Milestone 6: stochastic batch production

The deterministic benchmark uses expected batch success. Milestone 6 adds an
explicit stochastic layer without changing that benchmark:

```text
configs/litinski_stochastic_10mT.yaml
```

The 116-to-12 factory is treated as an all-or-nothing batch process:

```text
successful batch -> 12 usable states
failed batch     -> 0 usable states
P(success)       = 0.89
batch duration   = 99 * d * code_cycle
```

At `d=25` and a 1 microsecond code cycle:

```text
batch duration = 0.002475 s
successful batches required for 10M states = 833,334
```

The number of failures before those successful batches follows a negative
binomial distribution. This gives exact analytical runtime moments and a
vectorized Monte Carlo completion-time distribution.

For the configured 10,000-run seeded experiment:

```text
analytical mean runtime ~= 2317.4176 s
analytical runtime std  ~= 0.8420 s

Monte Carlo mean        ~= analytical mean
Monte Carlo p50/p95/p99 = reported by experiment
deadline                = 3600 s
observed deadline misses = reported, never interpreted as a true zero probability
```

When zero deadline misses are observed, the experiment also reports the
rule-of-three 95% upper heuristic (`3 / N`) so that "0 observed" is not
misstated as "impossible."

### Burst-aware event stream

`simulator.stochastic_factory.iter_batch_events()` exposes the underlying
batch process as discrete events. Every batch produces either 0 or 12 states.
This is the foundation for the next buffer/consumer model where queue depth,
starvation time, and burst absorption can be simulated explicitly.

### Current scope guardrail

Milestone 6 intentionally supports **one factory only** for the exact
completion-time Monte Carlo. Multi-factory synchronization and shared-buffer
behavior are not approximated away; they are deferred to a dedicated model.

## Scientific guardrails

- Historical regression fixtures remain immutable.
- Deterministic protocol benchmark remains separately reproducible.
- Stochastic runs use explicit seeds and configured run counts.
- "0 observed misses" is not reported as zero true probability.
- Final-batch quantization is kept explicit rather than hidden by a continuous-rate formula.
- Multi-factory behavior is not inferred from the one-factory distribution.

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
python -m experiments.stochastic_factory_runtime --config configs/litinski_stochastic_10mT.yaml
```

## Milestones

- [x] Config schema and historical regression baseline
- [x] Surface-code distance and floating-point boundary tests
- [x] Legacy factory regression fixture
- [x] Lower-bound resource metrics
- [x] Provenance-aware partial whole-machine accounting
- [x] Protocol-consistent factory timing, reliability, footprint, and STV
- [ ] Stochastic/burst-aware single-factory production
- [ ] Explicit magic-state buffer and consumer/starvation dynamics
- [ ] Multi-factory space-time trade-off search
- [ ] Static Pareto search
