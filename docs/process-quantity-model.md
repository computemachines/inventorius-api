# Process quantity model notes

This is a persistence-free design checkpoint. It does not define MongoDB, HTTP,
authorization, or frontend contracts.

## Decisions represented

- A process records only participating inputs and actual outputs. A source
  remainder is a derived holding state, never a process output.
- An input consumes either one exact amount or all quantity then feasible in one
  exact holding.
- An output may have an exact amount or reuse the compiled quantity of one
  input. Move and whole-Batch reclassification use the latter relationship.
- Every input must be accounted for by a holding output, an explicit external
  sink, or a structural contribution to an output. The model deliberately
  rejects a bare numerical withdrawal with no meaning.
- Several same-unit, same-package candidate Batches may satisfy one observed SKU
  selection. The compiler retains a latent allocation per candidate and one
  shared total instead of selecting a Batch or storing independent ranges.
- An audit produces non-consuming observations. Lower, upper, interval, exact,
  and preferred-only claims remain distinct.
- Assembly and disassembly use ordinary process inputs and outputs. Quantities
  in incompatible units are not added; structural provenance remains a
  separate relationship over the same process.
- Definition edits and descriptive properties are ordinary database records,
  outside the physical solver.
- Process cost, Batch cost, FIFO, average cost, and other accounting policies
  are a future projection over shared process identities and properties. They
  do not change physical quantity algebra.
- A late record is an ordinary process whose `occurred_at` precedes
  `recorded_at`. The timeline recompiles by occurrence time and may expose a
  contradiction in later history.
- Correction and conflict-resolution semantics remain deliberately deferred.
  The current experiment only retains and names contradictions.

## Intentional limitations

- Events with identical occurrence timestamps need an explicit causal-order
  design before persistence; the experiment uses deterministic ordering only
  so traces are reproducible.
- External sources are not modeled yet, so output-only Receive processes fail
  closed rather than manufacturing inventory from an unnamed source.
- The compiler receives an explicit candidate set for ambiguous SKU selection.
  A future identity/time resolver must determine those candidates from the SKU,
  location, evidence, and occurrence time.
- A process cannot consume from and produce into the identical holding in this
  slice. That case needs explicit semantics instead of an accidental ordering.
- An unresolved multi-Batch input cannot be collapsed into one concrete output
  Batch. A later allocation/identity design must preserve those possibilities
  through moves, splits, or transformations.
- Process definitions, provenance allocation modes, corrections, database
  codecs, and public operations remain outside this slice.
- Generated holding states, flow variables, allocation variables, intervals,
  witnesses, and conflicts are disposable projections. Only semantic events
  are candidates for future persistence.

## Running the traces

From `inventorius-api`:

```console
uv run python scripts/trace_process_solver.py
```

The trace prints replay order, generated relationships, sharp current bounds,
ambiguous per-Batch allocation, and the conflict caused by inserting a late
process before otherwise consistent later events.
