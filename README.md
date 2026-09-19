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

routing/interconnect spatial model
  -> explicit tile cost for factory-to-buffer connectivity

2D greedy floorplanner + A* pathfinder
  -> explicit block placement, obstacles, corridor reuse, and candidate layouts

finite-capacity interconnect dynamics
  -> pipelined transport, shared-cell contention, delayed arrivals, and STV feedback
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

## Milestone 12: routing/interconnect spatial cost

The Litinski tile framework makes connectivity part of the architecture rather
than a free abstraction: magic states must be moved through available tile
regions. Related resource-estimation work likewise treats multi-factory
placement as a 2D packing problem in which every factory needs a path to the
data block.

This milestone adds a deterministic first routing model instead of an arbitrary
percentage overhead.

### Manhattan trunk-and-spur v1

The named one-factory layout remains the embedded baseline and receives zero
*additional* routing tiles.

For every extra factory:

```text
factory tile area = 44
effective compact span = ceil(sqrt(44)) = 7 tiles
clearance = 1 tile
slot pitch = 8 tiles
branch spur = 1 tile
lane width = 1 tile

additional routing = 9 tiles / extra factory
```

Therefore:

```text
factories   additional routing tiles
1           0
2           9
3           18
4           27
```

Each routing tile is charged through the same configured tile-to-physical-qubit
mapping as the rest of the surface-code architecture.

At d=27 this means:

```text
9 routing tiles  -> 13,122 physical qubits
18 routing tiles -> 26,244 physical qubits
27 routing tiles -> 39,366 physical qubits
```

The routed benchmark is separate from the Milestone 11 benchmark:

```text
configs/litinski_multi_factory_pareto_10mT.yaml
  -> historical unrouted Milestone 11 result

configs/litinski_multi_factory_routed_pareto_10mT.yaml
  -> Milestone 12 spatial-routing result
```

The same Pareto engine is rerun after routing tiles are added **before** code
distance and physical-qubit accounting. This means routing can influence both
the direct footprint and, if a reliability boundary is crossed, the selected
code distance.

### Direct routed/unrouted comparison

`experiments/routing_pareto_comparison.py` joins candidates by architecture ID
and reports:

```text
routing tiles
routing physical qubits
routed vs unrouted physical-qubit delta
fractional footprint increase
code-distance changes
Pareto membership changes
risk-target reference-policy changes
```

This lets us test whether a previously attractive architecture survives its
explicit spatial interconnect cost instead of assuming that it does.

### First routed Pareto result: the preferred architecture can flip

The first comparison does **not** preserve every Milestone 11 reference design.

For moderate risk targets, explicit routing cost favors fewer factories and a
larger shared buffer:

```text
risk target   unrouted reference        routed reference
1e-2          N2_B048_STAG_I012         N1_B096_SYNC_I024
1e-4          N2_B048_SYNC_I024         N1_B096_SYNC_I048
1e-6          N3_B048_SYNC_I024         N2_B096_SYNC_I048
1e-9          N3_B048_STAG_I024         N2_B096_SYNC_I048
```

For the stricter targets, the reference designs remain unchanged:

```text
1e-12         N2_B096_STAG_I048
1e-18         N3_B096_STAG_I048
1e-24         N4_B096_STAG_I048
```

This is a cross-layer result: once interconnect space is charged explicitly,
"more factories with a smaller buffer" can lose to "fewer factories with a
larger buffer" even though the stochastic production model itself has not
changed.

For example, the routed 2-factory / 48-state architecture at d=27 adds 9
routing tiles = 13,122 physical qubits, raising its footprint from 427,194 to
440,316 physical qubits. The one-factory / 96-state architecture keeps the
embedded one-factory routing baseline and remains at 438,858 physical qubits.

The result should be interpreted as **model sensitivity**, not a final floorplan
claim: the exact geometry is still the explicit Manhattan lower-bound
assumption described below.

### Routing-model provenance

The **need** for routed connectivity is literature-grounded. The exact
`manhattan_trunk_and_spur_v1` geometry is deliberately labeled
`model_assumption`.

The compact span uses `ceil(sqrt(factory_tile_area))` as a reproducible
first-order envelope. It is **not** a claim that Litinski's 44-tile 116-to-12
factory is literally a 7-by-7 square.

Transport latency, path crossings, contention, detailed factory polygons, and
a full greedy 2D packing algorithm remain future refinements.

## Milestone 13: genuine 2D floorplanner + pathfinder

Milestone 12 deliberately used a simple Manhattan trunk-and-spur proxy. It was
useful because it proved that routing assumptions can change the Pareto answer,
but it did not actually place blocks or find paths around obstacles.

Milestone 13 adds a deterministic 2D tile-grid floorplanner.

### Exact-area geometry proxies

Every logical block receives an explicit occupied-cell polygon with exactly the
configured number of tiles:

```text
153-tile data block  -> compact raster inside a 13 x 12 envelope
44-tile factory      -> compact raster inside a 7 x 7 envelope
52-tile buffer       -> compact raster inside an 8 x 7 envelope
104-tile buffer      -> compact raster inside an 11 x 10 envelope
```

The compact-raster polygons are **model assumptions**, not claims about the
exact Litinski polygons. Their purpose is to let placement and routing operate
on real occupied cells without silently changing block tile counts.

### Greedy placement

The data block is anchored at the origin and the shared buffer is placed beside
it. Factories are then placed one at a time.

Each candidate placement must satisfy the configured one-tile block clearance.
The deterministic placement score is:

```text
1. minimum union of routing-corridor tiles
2. minimum floorplan bounding-box area
3. minimum new path length
4. minimum anchor offset from the buffer
5. deterministic coordinate tie-break
```

This is a genuine 2D placement search, though it is still greedy rather than a
global placement optimizer.

### Obstacle-aware A* routing

Every factory is routed to the shared buffer with 4-neighbor A* search.

Logical blocks are obstacles. Existing route cells are shareable, so the model
can discover corridor reuse instead of charging every factory an independent
linear trunk.

The data-block-to-buffer path is also explicitly routed and visualized.

For resource accounting, the named one-factory architecture remains the
embedded connectivity baseline. The full paths are generated for every layout,
but only routing-union tiles beyond the corresponding one-factory floorplan are
charged as additional routing resources.

### The important result: the Manhattan flip was model-sensitive

For a 48-state buffer:

```text
factories   Manhattan extra route tiles   2D floorplan extra route tiles
1           0                              0
2           9                              1
3           18                             2
4           27                             11
```

The A* floorplanner packs early factories around the shared buffer and reuses
short corridors. This materially lowers the routing penalty relative to the
linear trunk proxy.

For the 2-factory / 48-state architecture at d=27:

```text
unrouted                   427,194 physical qubits
Manhattan Milestone 12     440,316 physical qubits
2D floorplanner            428,652 physical qubits
```

That changes the Pareto interpretation again.

The floorplanned reference designs are:

```text
maximum P(any starvation)   floorplanned reference
1e-2                        N2_B048_STAG_I012
1e-4                        N2_B048_SYNC_I024
1e-6                        N3_B048_SYNC_I024
1e-9                        N3_B048_STAG_I024
1e-12                       N2_B096_STAG_I048
1e-18                       N3_B096_STAG_I048
1e-24                       N4_B096_STAG_I048
```

Within this first floorplanner, those reference policies match the unrouted
Milestone 11 choices rather than the Manhattan Milestone 12 choices.

That does **not** mean routing is irrelevant. It means the architecture decision
is sensitive to routing geometry, and the simplistic linear trunk was too
expensive for layouts where factories can be packed around the buffer.

### Floorplan metrics

Every candidate now reports:

```text
block placements (x, y, width, height)
individual route lengths
full routing-corridor union
charged incremental routing tiles
floorplan width / height
bounding-box area
active-tile packing density
```

A layout renderer can generate an actual 2D PNG:

```bash
python -m experiments.render_floorplan \
  --config configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml \
  --candidate N2_B048_STAG_I012 \
  --output results/floorplans/N2_B048_STAG_I012.png
```

### Three-model comparison

The repository now preserves three routing layers:

```text
unrouted
  -> no extra interconnect cost

Manhattan trunk-and-spur
  -> deterministic linear spatial proxy

greedy 2D floorplanner + A*
  -> explicit occupied cells + obstacle-aware paths
```

`experiments.floorplan_model_comparison` compares the reference architecture
selected by all three models for every configured risk target.

## Milestone 14: finite-capacity interconnect + transport latency

Milestone 13 allowed route sharing but treated shared corridors as temporally
free. Milestone 14 gives the 2D paths finite transport capacity and feeds the
result back into starvation risk, expected runtime, reliability, and STV.

### Pipelined cell-capacity model

The current benchmark assumes:

```text
1 magic state / route cell / logical time step
1 path-cell hop / logical time step
12 states / successful factory batch
```

Individual states pipeline through the A* route. If two routes use the same cell
at the same logical step, the finite-capacity reservation serializes them.

Simultaneous successful factories are scheduled round-robin by token index and
factory ID. This avoids silently giving a whole 12-state batch permanent
priority over the other factories.

The batch is still exposed to the shared buffer atomically only after its last
state arrives, preserving the earlier 116-to-12 batch semantics.

### Exact risk with intra-event transport arrivals

The transport-aware kernel no longer assumes factory output appears at the
buffer at factory-completion time.

For each factory event it branches over the exact Bernoulli success outcomes,
computes transport completion times from the actual 2D paths, serves consumer
demand up to each arrival, then admits the transported batch.

The model reports:

```text
P(any starvation)
expected starved service slots
expected stall intervals
expected overflow states
expected stall extension
single-batch transport latency
all-success contention latency
expected campaign runtime
expected campaign STV
```

Expected stall extension uses the same fixed-rate consumer semantics as the
earlier buffer model:

```text
expected stall extension
  = expected missed service slots / consumer issue rate
```

### Transport-aware code-distance selection

For every architecture and every allowed code distance, the simulator now
evaluates:

```text
nominal algorithm runtime
+ conservative prefill / phase startup
+ transport tail after final prefill production
+ expected transport-induced stall extension
```

The smallest code distance passing the configured whole-machine failure budget
is selected. Transport is therefore no longer reliability-free.

### Scope guardrail: no hidden in-flight truncation

This first exact transport kernel requires every produced batch to finish
transport before the next factory-completion event.

If a route/capacity combination spills across that event boundary, the
candidate is rejected as unsupported rather than silently dropping in-flight
network state.

A later network-state model can lift this restriction.

### Why this is the next digital-twin layer

Milestone 13 could answer:

```text
Where are the blocks?
Which cells form the routes?
How many route tiles are required?
```

Milestone 14 adds:

```text
When do transported states actually arrive?
Which shared cells serialize traffic?
How much starvation is caused by transport delay?
How much expected runtime and STV does that delay add?
```

This explicitly tests whether the spatially cheapest floorplan is also the
temporally best one.

### First transport-aware Pareto result

Finite transport latency leaves the moderate-risk reference policies stable:

```text
maximum P(any starvation)   floorplan zero-latency   finite-capacity transport
1e-2                        N2_B048_STAG_I012        N2_B048_STAG_I012
1e-4                        N2_B048_SYNC_I024        N2_B048_SYNC_I024
1e-6                        N3_B048_SYNC_I024        N3_B048_SYNC_I024
```

But the strict-risk region changes:

```text
1e-9   N3_B048_STAG_I024 -> N3_B048_SYNC_I048
1e-12  N2_B096_STAG_I048 -> N3_B096_SYNC_I048
1e-18  N3_B096_STAG_I048 -> N3_B096_STAG_I048
1e-24  N4_B096_STAG_I048 -> no candidate in current grid
```

So finite transport is not just a cosmetic latency term. It can change the
selected architecture once the starvation-risk requirement becomes strict.

For the 1% risk view:

```text
N2_B048_STAG_I012
P(any starvation) ~= 1.378617e-3
expected transport-induced stall extension ~= 1.72 microseconds
physical qubits = 428,652
```

The expected stall-time penalty is tiny even though the run-level probability
of at least one starvation event is measurable. This distinction is important:
"probability of any stall" and "expected total stall duration" are different
architecture metrics.

At the 1e-12 target, the transport-aware search moves to:

```text
N3_B096_SYNC_I048
P(any starvation) ~= 5.56e-18
physical qubits = 570,078
```

The current grid has no design meeting the 1e-24 target after finite transport
is included.

This is the first result in the project where an explicit temporal interconnect
model removes a previously feasible risk-target reference design.

## Milestone 15: persistent in-flight network state

Milestone 14 still had one deliberate simplification: every transported batch
had to finish before the next factory event. Milestone 15 removes that shortcut
at the network-scheduler layer.

### Absolute-time reservations survive event boundaries

The new `PersistentReservationNetwork` stores route-cell occupancy in absolute
network ticks. When a later factory event creates another batch, the new states
see every future cell-time reservation already created by older batches.

That means the simulator can now represent:

```text
batch A generated
  -> still moving through the interconnect

next factory event
  -> batch B generated

batch B
  -> sees batch A's future reservations
  -> waits or pipelines around them
```

Nothing is reset merely because a new factory event occurs.

### Mid-route waiting

Each magic state is scheduled hop by hop over the A* path.

If the next route cell is already occupied for the configured hop duration, the
state waits before entering that cell. The wait is recorded as contention delay.

Simultaneous batches are still scheduled round-robin by token index and factory
ID, so one whole 12-state batch does not receive hidden priority.

### Deterministic worst-case network stress

The first persistent-state benchmark intentionally uses:

```text
every scheduled factory batch succeeds
```

This is an all-success structural load test, not a stochastic probability
estimate. It asks whether the network can carry the maximum production pattern
without persistent backlog.

The configured scenarios are:

```text
2 factories / 48-state buffer / even staggered
3 factories / 48-state buffer / even staggered
4 factories / 96-state buffer / even staggered
```

with hop-latency sensitivity of 1, 2, and 4 logical time steps.

Even-staggered timing uses integer substeps of
`1 / factory_count` logical time steps, so the 99-step protocol period remains
exact without floating-point phase clocks.

### Persistent-network metrics

The stress experiment reports:

```text
maximum in-flight batches at factory-event boundaries
fraction of factory-event boundaries with in-flight transport
in-flight batches after the last generation event
network drain tail
mean / p95 / max batch latency
mean / max contention wait per state
busiest route-cell utilization
total reserved cell-time
```

These metrics describe the interconnect state itself. They are deliberately not
presented as replacements for the exact whole-computation starvation metrics
from Milestone 14.

### Scope boundary

Milestone 15 proves that transport state can persist across multiple factory
events.

It does not yet embed the full reservation/backlog state inside the exact
whole-run Markov starvation kernel. That coupling is a separate problem because
the state space is now much larger than buffer occupancy alone.

Waiting nodes also have unbounded temporary storage in this milestone. Finite
node-buffer capacity and backpressure remain future refinements.

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
- Persistent network reservations are exact for the configured deterministic
  scheduler, but waiting nodes currently have unbounded temporary storage.
- The all-success persistent-network benchmark is a structural worst-case load
  test, not a run-level probability estimate.

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

python -m experiments.multi_factory_pareto_search \
  --config configs/litinski_multi_factory_routed_pareto_10mT.yaml \
  --output-dir results/multi_factory_routed

python -m experiments.routing_pareto_comparison \
  --unrouted-config configs/litinski_multi_factory_pareto_10mT.yaml \
  --routed-config configs/litinski_multi_factory_routed_pareto_10mT.yaml \
  --output-dir results/routing_impact

python -m experiments.multi_factory_pareto_search \
  --config configs/litinski_multi_factory_floorplanned_pareto_10mT.yaml \
  --output-dir results/multi_factory_floorplanned

python -m experiments.floorplan_model_comparison

python -m experiments.transport_aware_pareto_search \
  --config configs/litinski_multi_factory_transport_pareto_10mT.yaml \
  --output-dir results/transport_aware_pareto

python -m experiments.inflight_network_stress \
  --config configs/litinski_inflight_network_stress.yaml \
  --output-dir results/inflight_network_stress
```

## Milestones

- [x] Historical regression baseline
- [x] Protocol-consistent deterministic benchmark
- [x] Stochastic/burst-aware single-factory production
- [x] Explicit magic-state buffer and consumer/starvation dynamics
- [x] Exact finite-state buffer-risk characterization
- [x] Initial-buffer prefill policy study
- [x] Automatic buffer/prefill Pareto policy search
- [x] Exact multi-factory shared-buffer Pareto search
- [x] Layout-aware factory-to-buffer routing/interconnect model
- [x] Routed/unrouted Pareto stability comparison
- [x] Greedy 2D packing / A* pathfinding floorplanner
- [x] Finite-capacity interconnect + transport latency
- [ ] Persistent in-flight network-state / multi-event transport queue
- [ ] Global placement optimization
- [ ] Adaptive / dynamic factory provisioning
