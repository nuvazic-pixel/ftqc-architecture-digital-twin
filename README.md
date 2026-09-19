# FTQC Architecture Digital Twin

A reproducible simulator for fault-tolerant quantum-computing (FTQC) architecture co-design.

## Model layers

The repository preserves each scientific layer instead of rewriting earlier
results:

```text
historical regression baseline
  -> stability checks

protocol-consistent Litinski benchmark
  -> named deterministic architecture

stochastic single-factory benchmark
  -> batch success/failure runtime distribution

buffer + consumer dynamics
  -> bounded queue, overflow, starvation, footprint/reliability coupling

exact buffer-risk characterization
  -> finite-state probability of starvation over the nominal execution
```

## Milestone 8: exact buffer-risk characterization

The original plan was to run many random seeds. For the current bounded
single-factory model, that is unnecessary: buffer occupancy has a small finite
state space and the consumer schedule is exactly periodic.

Milestone 8 therefore computes the starvation probability directly with a
finite-state Markov model. This removes Monte Carlo sampling error for the
current assumptions.

### Exact periodic consumer schedule

For d=25:

```text
batch duration = 2,475,000 ns
consumer demand = 10,000,000 states / 3600 s

exact service pattern over 8 batches:
6, 7, 7, 7, 7, 7, 7, 7
sum = 55 states
```

For d=27 the exact service schedule has a 40-batch period.

### Why log-space survival matters

Small buffers make "no starvation for the full run" fantastically unlikely.
A normal float underflows long before the real probability reaches zero.

The exact-risk engine therefore retains the survival probability in log space.

For example:

```text
24-state buffer:
log10 P(no starvation) ~= -891.7425
```

So the linear float is 0 by underflow, but the simulator does **not** interpret
that as mathematical impossibility.

### Exact one-hour starvation risk

Starting with an empty buffer, under the current independent-batch model:

```text
buffer   d    physical qubits   P(any starvation)
12       25      262,500        ~1.000000
24       25      278,750        ~1.000000
48       25      311,250        ~0.9296313
96       27      438,858        ~0.2397476
```

This changes the interpretation of the single seed from Milestone 7.

The seed-42 trace with a 48-state buffer had only a tiny starvation extension,
but exact risk analysis shows that **some starvation occurs in about 93% of
runs** under the same model. The stochastic trace was reproducible; it simply
was not representative of run-level risk.

Likewise, the 96-state trace had zero starvation, while the exact model gives
roughly 24% probability of at least one starvation event when starting empty.

That is precisely why statistical characterization was required before moving
to multi-factory optimization.

### Primary metric definition

`probability_any_starvation` means:

> probability that at least one scheduled consumer service slot cannot be
> filled before the quantized nominal completion time.

Unavoidable final-batch time quantization is excluded from this metric. Under
the fixed-rate consumer model, any starvation event implies positive
starvation extension.

### Scientific guardrails

- This is exact **within the stated single-factory Markov model**.
- Batch successes are still assumed independent with constant p=0.89.
- Initial buffer occupancy is explicit; the current benchmark starts empty.
- Buffer-storage layout scaling remains a model assumption.
- Routing/placement cost of replicated storage remains incomplete.
- A float underflow in survival probability is accompanied by log10 survival.
- Exact risk does not validate the physical independence assumption itself.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pytest

python -m experiments.litinski_minimal_setup --config configs/litinski_minimal_10mT.yaml
python -m experiments.stochastic_factory_runtime --config configs/litinski_stochastic_10mT.yaml
python -m experiments.buffer_sensitivity --config configs/litinski_buffer_10mT.yaml
python -m experiments.buffer_risk_characterization --config configs/litinski_buffer_risk_10mT.yaml
```

## Milestones

- [x] Historical regression baseline
- [x] Protocol-consistent deterministic benchmark
- [x] Stochastic/burst-aware single-factory production
- [x] Explicit magic-state buffer and consumer/starvation dynamics
- [ ] Exact finite-state buffer-risk characterization
- [ ] Initial-buffer / prefill policy study
- [ ] Multi-factory space-time trade-off search
- [ ] Static Pareto search
