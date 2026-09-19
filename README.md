# FTQC Architecture Digital Twin

A reproducible simulator for fault-tolerant quantum-computing (FTQC) architecture co-design.

## Current model stack

```text
historical regression baseline
  -> stability checks

protocol-consistent Litinski benchmark
  -> deterministic named architecture

stochastic factory
  -> bursty batch completion

buffer + consumer dynamics
  -> bounded queue and starvation

exact finite-state buffer risk
  -> no Monte Carlo sampling error within the model

initial-buffer prefill policy
  -> startup latency versus starvation-risk trade-off

automatic policy Pareto search
  -> multi-objective buffer/prefill co-design

multi-factory shared-buffer co-design
  -> exact phase-aware risk across factory count, buffer, and startup
```

## Milestone 11: exact multi-factory shared-buffer Pareto search

Milestone 11 introduces 1-4 independent 116-to-12 factories feeding one bounded
shared magic-state buffer.

The candidate grid jointly varies:

```text
factory count        1, 2, 3, 4
buffer capacity      48, 96 states
initial buffer       12, 24, 48 states
phase policy         synchronized / even_staggered
```

The one-factory case uses only the synchronized policy, leaving 42 total
candidates.

### Phase policy is now an architecture variable

Two timing policies are modeled:

```text
synchronized:
  all factories finish together once per protocol batch
  arrival count per event ~ Binomial(N_factory, 0.89)

even_staggered:
  factory completion phases are evenly spaced
  one factory completes per event
  each event ~ Bernoulli(0.89)
```

For staggered operation, the phase-establishment time is explicit:

```text
phase setup = batch_duration * (N_factory - 1) / N_factory
```

The startup accounting conservatively adds phase setup and expected prefill
latency rather than assuming they overlap for free.

### Causal event ordering

The multi-factory model uses:

```text
consumer demand accrued since previous event
  -> service from existing buffer
  -> detect starvation if demand is unmet
  -> admit newly completed factory output
```

This is intentionally more causal than allowing a batch completing at the end
of an interval to satisfy demand that occurred earlier in that interval.

### Phase staggering can buy risk reduction without more qubits

For 2 factories, a 48-state buffer, 12 initial states, and d=27:

```text
policy          physical qubits   startup      P(any starvation)
synchronized       427,194        ~2.706 ms    ~1.2146e-2
even_staggered     427,194        ~2.838 ms    ~1.3785e-3
```

The physical footprint is identical. A small increase in conservative startup
latency reduces starvation risk by almost an order of magnitude under the
current model.

That is a scheduling/architecture effect, not a hardware-count effect.

### Constraint-driven reference designs

The Pareto objectives are:

```text
physical qubits                     minimize
conservative startup latency         minimize
log10 P(any starvation)              minimize
```

The current discrete grid gives the following reference designs:

```text
maximum P(any starvation)   reference
1e-2                        N2_B048_STAG_I012
1e-4                        N2_B048_SYNC_I024
1e-6                        N3_B048_SYNC_I024
1e-9                        N3_B048_STAG_I024
1e-12                       N2_B096_STAG_I048
1e-18                       N3_B096_STAG_I048
1e-24                       N4_B096_STAG_I048
```

For example:

```text
N2_B048_STAG_I012
= 2 factories
= 48-state shared buffer
= even-staggered phases
= 12 initial magic states
```

No weighted score chooses these policies. A risk constraint is supplied first;
the reference is then selected by minimum physical qubits, minimum conservative
startup latency, and finally minimum starvation probability.

### Reliability and distance are coupled to startup

Code distance is selected separately for every candidate.

The model tests each allowed distance against:

```text
nominal 3600 s execution
+ conservative startup time
```

under the whole-machine logical-failure budget. Startup is therefore not
treated as reliability-free.

### New numerical guardrail for very small risk

Earlier single-factory milestones needed log-space **survival** because
no-starvation probability could be fantastically small.

Multi-factory designs can enter the opposite regime where starvation
probability is tiny.

Milestone 11 therefore uses an explicit absorbing starvation state and reads
`P(any starvation)` directly from that state instead of calculating
`1 - P(no starvation)`. This avoids catastrophic cancellation for risks down
to roughly 1e-25 in the current grid.

### Visualizations and outputs

The experiment writes:

```text
multi_factory_pareto.json
multi_factory_candidates.csv
multi_factory_pareto.csv

multi_factory_qubits_vs_risk.png
multi_factory_startup_vs_risk.png
```

Both plots use logarithmic starvation-risk axes.

## Scientific guardrails

- Batch successes remain independent with constant p=0.89.
- Even staggering assumes deterministic, evenly spaced factory phases.
- Phase setup + prefill is a conservative non-overlap startup model.
- Shared-buffer storage replaces per-factory output storage in this milestone.
- Additional multi-factory routing/interconnect tiles are still **unmodeled**.
- Physical-qubit counts are therefore optimistic architecture-model lower bounds.
- The event-order convention is explicit and can be sensitivity-tested later.
- The frontier is exact only for the configured discrete design grid.
- Nominal campaign STV does not include stochastic post-starvation runtime extension.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest

python -m experiments.multi_factory_pareto_search \
  --config configs/litinski_multi_factory_pareto_10mT.yaml \
  --output-dir results/multi_factory_pareto

python -m experiments.plot_multi_factory_pareto \
  --config configs/litinski_multi_factory_pareto_10mT.yaml \
  --output-dir results/multi_factory_pareto
```

## Milestones

- [x] Historical regression baseline
- [x] Protocol-consistent deterministic benchmark
- [x] Stochastic/burst-aware single-factory production
- [x] Explicit magic-state buffer and consumer/starvation dynamics
- [x] Exact finite-state buffer-risk characterization
- [x] Initial-buffer prefill policy study
- [x] Automatic buffer/prefill Pareto policy search
- [ ] Exact multi-factory shared-buffer Pareto search
- [ ] Layout-aware factory-to-buffer routing/interconnect model
- [ ] Adaptive / dynamic factory provisioning
