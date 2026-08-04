# Process quantity model notes

This is a persistence-free design checkpoint. It does not define MongoDB, HTTP,
authorization, or frontend contracts.

## Decisions represented

- A process records only participating inputs and actual outputs. A source
  remainder is a derived holding state, never a process output.
- Receive crosses a named external-source boundary. Its quantity is an
  observation with exact, bounded, or preferred evidence; it is not anonymous
  creation and is linked algebraically to the received holding.
- An input consumes either one exact amount or all quantity then feasible in one
  exact holding.
- An output may have an exact amount or reuse the compiled quantity of one
  input. Move and whole-Batch reclassification use the latter relationship.
- Every input must be accounted for by a holding output, an explicit external
  sink, or a structural contribution to an output. The model deliberately
  rejects a bare numerical withdrawal with no meaning.
- Several same-unit, same-package candidate Batches may satisfy one observed SKU
  selection. The durable semantic fact is the SKU/location selection plus the
  candidate snapshot known when it was recorded. A knowledge-aware resolver can
  add a Batch discovered later, while historical compilation retains the old
  candidate set. The compiler retains a latent allocation per candidate and one
  shared total instead of selecting a Batch or storing independent ranges.
- An identity-preserving move maps every latent source allocation to a holding
  of that same Batch at the destination. The moved total can therefore be exact
  while the destination's per-Batch composition remains ranged.
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
- Physical replay uses `(occurred_at, effective_order)`. Recording time filters
  historical knowledge but never silently chooses physical order. Equal-time,
  equal-order events may remain unordered only when their holdings are disjoint;
  overlapping events fail closed.
- Whole-Batch reclassification is retained as one Batch-replacement meaning and
  expanded during replay across every then-current holding. A late-discovered
  source holding is therefore reclassified on current-truth replay rather than
  being permanently omitted from a frozen list of holding legs.
- Correction and conflict-resolution semantics remain deliberately deferred.
  The current experiment only retains and names contradictions.

## Intentional limitations

- `effective_order` is a deliberately small ordering mechanism, not a final
  claim that integer sequence numbers will be sufficient for concurrent or
  partially ordered physical histories.
- One external source feeds one output in this slice. Split receipts and
  multi-output boundary allocation still need explicit flow semantics.
- The experiment defines the knowledge-aware candidate-resolver seam, not the
  database implementation that will resolve SKU membership and presence at the
  event's occurrence time.
- A process cannot consume from and produce into the identical holding in this
  slice. That case needs explicit semantics instead of an accidental ordering.
- An unresolved multi-Batch input cannot be collapsed into one concrete output
  Batch. Identity-preserving moves now retain the alternatives; transformations
  that merge, split, or replace those identities remain fail-closed.
- Process definitions, provenance allocation modes, corrections, database
  codecs, and public operations remain outside this slice.
- Batch replacement currently preserves location, unit, and package
  configuration. Reclassification that also changes those dimensions should be
  an ordinary explicit transformation, not hidden inside identity replacement.
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
