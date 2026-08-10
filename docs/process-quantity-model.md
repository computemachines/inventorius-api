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
- An output may have an exact amount, preserve one input Batch and its compiled
  quantity, or explicitly create one new Batch under a declared one-to-one
  transformation assertion. This assertion is stored with the event; it is not
  a reference to a separately authoritative basis. Matching unit names alone
  never establish a Batch or SKU transformation.
- Every input must be accounted for by a holding output, an explicit external
  sink, or a structural contribution to an output. The model deliberately
  rejects a bare numerical withdrawal with no meaning. One input may have only
  one quantitative destination until explicit split-allocation semantics exist.
- Several same-unit, same-package candidate Batches may satisfy one observed SKU
  selection. The durable semantic fact is the SKU/location selection plus the
  candidate snapshot known when it was recorded. A knowledge-aware resolver can
  add a Batch discovered later, while historical compilation retains the old
  candidate set. The compiler retains a latent allocation per candidate and one
  shared total instead of selecting a Batch or storing independent ranges.
- An identity-preserving move maps every latent source allocation to a holding
  of that same Batch at the destination. The moved total can therefore be exact
  while the destination's per-Batch composition remains ranged.
- A declared one-to-one transformation may take an exact total from several
  candidate Batches of one SKU and create one fresh Batch in a different SKU.
  Each candidate allocation remains the source allocation for the new Batch.
  A later audit can therefore tighten both source remainders and the earlier
  output's source attribution without rewriting the process.
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
  overlapping events fail closed. A whole-Batch replacement overlaps every
  event touching either Batch identity, including holdings first introduced in
  that same replay group.
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
  event's occurrence time. The caller-declared transformation snapshot names
  source and output SKUs, but later integration must verify each referenced
  Batch against the catalog; `HoldingKey` deliberately does not duplicate
  Batch-to-SKU ownership.
- A process cannot consume from and produce into the identical holding in this
  slice. That case needs explicit semantics instead of an accidental ordering.
- The only identity-merging transformation in this slice has one process-input
  leg with an exact total (possibly allocated among several candidate Batches),
  one fresh output Batch, the same unit and quantity domain, one-to-one yield,
  and no loss. Unit conversions, variable yield, homogeneous blending, losses,
  byproducts, and splitting one quantitative flow among multiple destinations
  remain fail-closed. This does not prohibit multiple explicit structural
  assembly or disassembly outputs.
- Process definitions, general provenance allocation modes, corrections,
  database codecs, and public operations remain outside this slice.
- Batch replacement currently preserves location, unit, and package
  configuration. Reclassification that also changes those dimensions should be
  an ordinary explicit transformation, not hidden inside identity replacement.
- Generated holding states, flow variables, candidate allocations, output
  source-allocation variables, intervals, witnesses, and conflicts are
  disposable projections. Only semantic events and their declared
  transformation assertions are candidates for future persistence.

## Running the traces

From `inventorius-api`:

```console
uv run python scripts/trace_process_solver.py
```

The trace prints replay order, generated relationships, sharp current bounds,
ambiguous per-Batch allocation, an ambiguity-preserving transformation with a
later tightening audit, and the conflict caused by inserting a late process
before otherwise consistent later events.
