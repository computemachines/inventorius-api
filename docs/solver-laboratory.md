# Constraint solver laboratory

The solver is developed first as a persistence-free function:

```text
answer(frozen graph, temporary overlay, structured query) -> structured result
```

Recording a process or observation only adds a fact to the graph. It does not
run the solver, update a materialized quantity, or populate a cache. A read
compiles one disposable solver from a frozen graph revision, answers one
structured query, and discards it. Multi-query batching may later reuse one
fresh reconstruction, but it must preserve exactly the same feasible set.

## Four independently testable layers

1. **Mathematical kernel** -- exact nonnegative variables, named linear
   constraints, feasibility, bounds, witnesses, conflicts, and timeouts.
2. **Event compiler** -- physical processes and non-consuming observations
   become the intended variables and constraints.
3. **Later query compiler** -- typed selectors, unions, lineage, grouping, and
   physical- and knowledge-time scope become solver expressions.
4. **Physical scenarios** -- complete physical constraint graphs and queries
   are compared with an implementation-independent reference oracle.

A failure should identify which boundary is wrong. Kernel tests must not depend
on the event compiler, and query tests must not manufacture their expected
answers by calling the production compiler a second way.

This initial slice implements the layer below those semantic selectors:
immutable revisioned snapshots, disposable constraint overlays, exact linear
expressions, sharp-bound queries, threshold predicates, and counterfactual
feasibility classification. Batch/SKU/bin selectors, set unions, transitive
lineage, and grouping are later query-compiler work, not claims of this slice.

## Independent finite-world oracle

For deliberately small integer examples, a slow Python oracle enumerates every
physically allowed history using ordinary loops. It neither imports Z3 nor
reuses the production event or query compiler. The oracle evaluates the query
in each feasible history and returns the minimum and maximum of those concrete
answers.

Agreement with the production solver is exact. If enumeration says `23..25`
and the production solver says `24..25`, the test fails; there is no error
tolerance. Enumeration remains a test oracle, not a production execution path.

## Golden experiments

### Query-specific LED precision

The opening bin contains exactly 25 red and 25 blue LEDs. Part A uses 24 LEDs
and Part B uses 25, without recording their color allocations. The two parts
are separate Batches of the same output SKU.

- red in A: `0..24`
- red in B: `0..25`
- red in the union of A and B: `24..25`
- after both enter final Batch F, red ancestry in F: `24..25`

The union is queried directly. The application must never add the two displayed
component ranges, because that discards their shared constraints. If a later
observation says the one remaining source-bin LED is blue, the same final query
returns exactly 25 red LEDs. The individual part allocations may remain vague.

### Two-stage partial-use stress case

A harder experiment starts with exactly 12 red and 12 blue LEDs. Three
color-untracked intermediate Batches contain 8, 7, and 6 loose one-LED modules.
A final process then draws 7, 7, and 6 modules from those Batches. Three LEDs
remain in the source holding and one remains in the first intermediate Batch.
No LED is created or lost.

Before any later observation, the red ancestry of the final 20-LED assembly is
`8..12`. The red contributions from the three intermediate Batches are still
individually as vague as `0..7`, `0..7`, and `0..6`.

A later audit observes exactly one blue LED in the **union of every holding
outside the final assembly**: the three source leftovers plus the one
intermediate leftover. A fresh query then proves that the final assembly has
exactly 9 red and 11 blue ancestors. Nevertheless, every individual Batch
composition and contribution range remains unchanged. Even the source blue
remainder and intermediate blue remainder are each `0..1`; only their direct
union query is exactly one.

The production-side experiment states only local opening conservation,
per-Batch color totals and splits, and final aggregation. It does not add a
shortcut equation between the final and outside totals. An independent bounded
enumerator checks all 1,008 aggregate assignments: 340 histories are feasible
before the audit and 86 afterward. A generated collection of smaller histories
also checks the same graph shape against closed-form physical bounds.

This proves that the linear kernel and query boundary preserve correlations
through a correctly encoded two-stage graph. It does **not** yet prove that the
event compiler can construct that graph from recorded Processes, or that a
future semantic Batch-lineage query compiler selects the correct variables.
Those remain separate integration gates.

Follow-on experiments will introduce ranged opening quantities, named source
Batches, explicit loss, late-recorded evidence with physical- and
knowledge-time scopes, and event-compiled transitive lineage.

### Proposed move

A move of 20 items is compiled as a temporary event over a frozen base graph:

- source quantity `20..30`: compatible in every feasible base history;
- source quantity `10..30`: compatible in some histories but not guaranteed;
- source quantity `0..19`: contradicts every base history.

The preview never mutates the base graph. If the physical move already occurred,
the record may still be appended even when it exposes inconsistent prior facts;
the contradiction is forensic evidence, not permission to invent a quantity.

### Counterfactual conflict

Compile hypothetical processes X, Y, and Z plus observation A as a disposable
overlay. This slice compares base feasibility with augmented feasibility and
returns one deletion-minimal set of incompatible constraint IDs. The independent
finite-world oracle also tests the later event-level questions: whether Y alone
conflicts, whether removing Y restores feasibility, and whether Y belongs to one
or every deletion-minimal conflict. A conflict identifies jointly incompatible
facts; it does not declare which real-world record is wrong.

## Correctness gates

The laboratory treats these as release-blocking properties:

- adding consistent evidence only narrows an answer; incompatible evidence
  produces a conflict;
- removing evidence only widens an answer or restores feasibility;
- consistent identifier renaming, disconnected facts, and reordering
  independent events do not change an answer;
- a direct union query may be sharper than arithmetic over displayed ranges;
- every finite endpoint has a feasible witness;
- every reported conflict is contradictory, and every deletion-minimal conflict
  becomes feasible when any one of its facts is removed;
- a counterfactual overlay cannot mutate its base snapshot;
- repeated queries at one revision agree, and later evidence cannot contaminate
  an earlier revision;
- unsupported query shapes fail closed during validation, and solver timeouts
  return an indeterminate result rather than an approximation.

Run the Mongo-free lane with:

```text
make test-solver
```

The target deliberately excludes the repository-level `conftest.py`, whose
fixtures require MongoDB, and runs the existing pure quantity, process, and
provenance tests together with `tests/solver/`.

Correctness comes before performance work. We will later record graph size,
variable and constraint counts, compilation time, solving time, memory, and
timeouts using representative larger histories. Those measurements must not
introduce proactive computation, cached answers, or materialized solver state.
