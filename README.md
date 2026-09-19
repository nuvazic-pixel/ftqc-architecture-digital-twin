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
```

## Milestone 9: initial-buffer prefill policy

Milestone 9 asks a practical architecture question:

> Is it better to build a larger buffer, or start computation only after a
> smaller/larger buffer has been partially prefilled?

The exact finite-state model already accepts an initial occupancy, so this
milestone sweeps:

```text
0%, 25%, 50%, 75%, 100% initial fill
```

for 12-, 24-, 48-, and 96-state buffers.

### Prefill itself is batch-quantized

A 116-to-12 factory cannot create fractional protocol batches.

For example, requesting only 3 initial states still requires one successful
12-state batch. The model retains 3 and explicitly counts 9 discarded states.

Expected prefill latency is derived from the same negative-binomial batch model
as the stochastic factory:

```text
E[prefill attempts] = required successful batches / 0.89
```

### Key result: prefill cannot repair every undersized buffer

For the 48-state buffer:

```text
initial fill   P(any starvation)
0%             ~0.9296313
25%            ~0.9110559
50%            ~0.9096579
75%            ~0.9096314
100%           ~0.9096308
```

Even a completely full 48-state buffer still has about 91% probability of at
least one starvation event. The capacity itself is structurally too small for a
low-starvation-risk policy under the current assumptions.

### Key result: prefill is extremely effective once capacity is sufficient

For the 96-state buffer, which already requires d=27:

```text
initial fill   P(any starvation)     expected prefill
0%             ~2.397476e-1          0 ms
25%            ~1.062118e-3          6.01 ms
50%            ~5.302191e-5         12.01 ms
75%            ~5.114823e-5         18.02 ms
100%           ~5.114388e-5         24.03 ms
```

So under this model, a 25% prefill cuts risk by more than two orders of
magnitude for only a few milliseconds of expected startup latency. Moving from
50% to 100% provides almost no additional risk reduction.

This is the first clear policy-level trade-off exposed by the digital twin:
hardware capacity and initialization policy cannot be optimized independently.

### Reliability accounting guardrail

The current prefill benchmark conservatively assumes the full modeled machine
remains protected during prefill. The expected prefill time is therefore added
as a small failure-budget increment.

This is deliberately conservative. A future layout-aware startup model may
allow parts of the data block to remain inactive until computation begins.

### Scientific guardrails

- Exact starvation risk is exact only within the finite-state model.
- Independent batch success with constant p=0.89 remains an assumption.
- Prefill requests are protocol-batch quantized.
- Unused states from the final prefill batch are explicitly reported.
- Prefill latency is stochastic; this milestone reports analytical mean/std.
- Full-machine-active-during-prefill is a conservative modeling assumption.
- Buffer-storage scaling and missing replicated-storage routing remain explicit
  architecture limitations.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest

python -m experiments.buffer_risk_characterization --config configs/litinski_buffer_risk_10mT.yaml
python -m experiments.prefill_policy_sensitivity --config configs/litinski_prefill_policy_10mT.yaml
```

## Milestones

- [x] Historical regression baseline
- [x] Protocol-consistent deterministic benchmark
- [x] Stochastic/burst-aware single-factory production
- [x] Explicit magic-state buffer and consumer/starvation dynamics
- [x] Exact finite-state buffer-risk characterization
- [ ] Initial-buffer prefill policy study
- [ ] Multi-factory space-time trade-off search
- [ ] Static Pareto search
