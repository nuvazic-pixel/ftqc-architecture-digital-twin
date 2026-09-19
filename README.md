# FTQC Architecture Digital Twin

A reproducible simulator for fault-tolerant quantum-computing (FTQC) architecture co-design.

## Stable layers

The repository now keeps three distinct model layers instead of overwriting old
results:

```text
historical baseline
  -> regression stability

named Litinski benchmark
  -> protocol-consistent deterministic resource model

stochastic factory benchmark
  -> batch success/failure and runtime distributions
```

## Milestone 7: explicit buffer + consumer dynamics

Milestone 7 adds the first coupled producer / bounded-buffer / consumer model:

```text
factory batch
   |
   v
bounded magic-state buffer
   |
   v
fixed-rate algorithm consumer
```

The consumer rate is derived from the workload target rather than a free magic
number:

```text
10,000,000 states / 3600 s
```

A consumer service opportunity that is missed because the buffer is empty is
not carried forward. This means starvation creates real wall-clock extension;
the consumer cannot recover with unbounded catch-up later.

### Numerically exact service schedule

The fixed-rate schedule is implemented with integer nanoseconds and an integer
accumulator. This avoids a subtle source of floating-point drift where a nominal
6/7-state-per-batch pattern can change solely because 0.002475 s is not exactly
representable in binary floating point.

### Buffer-storage sensitivity model

The cited minimal layout has 13 storage tiles for the 12-state factory output.
For sensitivity only, larger buffers linearly replicate that storage block:

```text
12 states -> 13 storage tiles
24 states -> 26 storage tiles
48 states -> 52 storage tiles
96 states -> 104 storage tiles
```

This scaling is explicitly labeled `model_assumption`. Extra placement and
routing cost for replicated buffers is not yet modeled, so the footprint is a
sensitivity-model lower bound rather than a final physical layout.

### Coupled reliability effect

A larger buffer is not automatically better. More storage tiles increase the
number of simultaneously protected logical patches, which can tighten the
whole-machine reliability budget.

For the configured 1-hour design budget:

```text
capacity 12 -> d=25
capacity 24 -> d=25
capacity 48 -> d=25
capacity 96 -> d=27
```

That d=25 to d=27 jump is exactly the kind of cross-layer architectural effect
the digital twin is intended to expose.

### Seeded sensitivity trace

With seed 42 and the current discard-on-overflow policy:

```text
buffer   d    physical qubits   starvation extension
12       25      262,500        ~138.28 s
24       25      278,750        ~3.71 s
48       25      311,250        ~0.002475 s
96       27      438,858         0 s
```

These four values are one reproducible stochastic trace, not probability
estimates. A later milestone will run multi-seed / rare-event analysis.

The experiment also rechecks the logical-failure budget using the actual
post-stall completion time. Distance is selected from the design-time runtime
budget, never from a favorable random trajectory.

## Scientific guardrails

- Historical regression fixtures remain immutable.
- Protocol-consistent deterministic results remain separately reproducible.
- Stochastic seeds are explicit.
- Buffer overflow is currently `discard`, not silently backpressured.
- Buffer storage scaling is an explicit sensitivity assumption.
- Missing storage-placement/routing cost is not presented as modeled.
- Raw 3600-second deadline slip is separated from unavoidable batch-time
  quantization.
- Code distance is selected from a design budget and revalidated after the
  stochastic trace.

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
python -m experiments.buffer_sensitivity --config configs/litinski_buffer_10mT.yaml
```

## Milestones

- [x] Config schema and historical regression baseline
- [x] Surface-code distance and floating-point boundary tests
- [x] Legacy factory regression fixture
- [x] Lower-bound resource metrics
- [x] Provenance-aware partial whole-machine accounting
- [x] Protocol-consistent factory timing, reliability, footprint, and STV
- [x] Stochastic/burst-aware single-factory production
- [ ] Explicit magic-state buffer and consumer/starvation dynamics
- [ ] Multi-seed buffer-risk characterization
- [ ] Multi-factory space-time trade-off search
- [ ] Static Pareto search
