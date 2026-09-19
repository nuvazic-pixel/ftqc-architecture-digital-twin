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
  -> multi-objective co-design over hardware, startup, and risk
```

## Milestone 10: automatic policy Pareto search

Milestone 10 stops treating the 20 buffer/prefill policies as a table that a
human must inspect manually. Every candidate is now automatically classified
as Pareto-optimal or dominated.

The search jointly optimizes:

```text
physical qubits                         minimize
expected prefill latency                minimize
log10 P(no starvation)                  maximize
```

The log survival metric is deliberate. For tiny buffers, linear
`P(any starvation)` can round to exactly 1.0 even though the no-starvation
probability is mathematically nonzero. Pareto filtering therefore operates on
the underflow-safe log-space quantity while still reporting ordinary
probabilities for interpretation and plots.

### Batch quantization creates free policy improvements

The automatic search exposes a subtle effect that is easy to miss manually.

For a 12-state buffer, 25%, 50%, 75%, and 100% prefill all require exactly one
successful 12-state factory batch. Therefore 100% prefill has the same expected
startup latency and the same physical hardware as the smaller nonzero fills,
but lower starvation risk.

Those 25/50/75% policies are strictly dominated.

The same effect occurs for the 24-state buffer:

```text
25% and 50% -> one successful prefill batch
75% and 100% -> two successful prefill batches
```

so 50% dominates 25%, and 100% dominates 75%.

This is exactly the kind of discrete protocol effect that continuous
optimization would miss.

### Constraint-driven reference policies

The Pareto engine does not invent a single universal "best" design. Instead it
can answer explicit risk-target questions using a deterministic selection rule:

```text
minimum physical qubits
then minimum expected prefill latency
then minimum starvation probability
```

For the current search grid:

```text
maximum P(any starvation)   reference policy
1e-1                        B096_F025
1e-2                        B096_F025
1e-3                        B096_F050
1e-4                        B096_F050
1e-5                        no candidate in current grid
```

Policy IDs encode buffer and fill:

```text
B096_F025 = 96-state buffer, 25% prefill
B096_F050 = 96-state buffer, 50% prefill
```

This makes the recommendation traceable to an explicit risk requirement rather
than to an opaque weighted score.

### Visualizing the frontier

The plotting experiment creates two separate figures:

```text
results/policy_pareto/pareto_qubits_vs_risk.png
results/policy_pareto/pareto_prefill_vs_risk.png
```

Both use a logarithmic starvation-risk axis and distinguish dominated policies
from Pareto-frontier policies.

The first shows the hardware/risk trade-off. The second shows startup/risk.
Together they expose all three objectives without hiding one inside a weighted
scalar score.

### Machine-readable outputs

The search also writes:

```text
policy_pareto.json
policy_candidates.csv
policy_pareto.csv
```

so later multi-factory optimization and paper figures can consume the exact
same candidate set.

## Scientific guardrails

- Pareto dominance is applied only to explicit configured objectives.
- No hidden objective weights or arbitrary aggregate score are used.
- Log-space survival prevents numerical underflow from changing dominance.
- Risk-target reference policies are selected only after the risk constraint is
  supplied explicitly.
- Prefill and buffer layout assumptions from earlier milestones remain visible.
- The frontier is exact for the current discrete candidate grid, not proof of a
  global continuous optimum.
- Multi-factory synchronization remains outside this milestone.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest

python -m experiments.policy_pareto_search \
  --config configs/litinski_policy_pareto_10mT.yaml \
  --output-dir results/policy_pareto

python -m experiments.plot_policy_pareto \
  --config configs/litinski_policy_pareto_10mT.yaml \
  --output-dir results/policy_pareto
```

## Milestones

- [x] Historical regression baseline
- [x] Protocol-consistent deterministic benchmark
- [x] Stochastic/burst-aware single-factory production
- [x] Explicit magic-state buffer and consumer/starvation dynamics
- [x] Exact finite-state buffer-risk characterization
- [x] Initial-buffer prefill policy study
- [ ] Automatic buffer/prefill Pareto policy search
- [ ] Multi-factory space-time trade-off search
- [ ] Adaptive policy / dynamic factory provisioning
