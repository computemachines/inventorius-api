#!/usr/bin/env python3
"""Print concrete process/observation traces from the experimental compiler."""

from datetime import datetime, timezone

from inventorius.ledger import HoldingKey
from inventorius.process_quantities import (
    ALL_REMAINING,
    ExactAmount,
    FromInput,
    ObservationEvent,
    ProcessEvent,
    ProcessInput,
    ProcessOutput,
    ProcessQuantityTimeline,
    ProcessSink,
)
from inventorius.quantity_constraints import (
    InfeasibleQuantityFacts,
    ObservationBasis,
    QuantityDomain,
    QuantityObservation,
)


DISCRETE = QuantityDomain.DISCRETE


def time(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=timezone.utc)


def exact(event_id: str, holding: HoldingKey, amount: int, day: int):
    return ObservationEvent(
        holding,
        DISCRETE,
        QuantityObservation.exact(
            event_id,
            amount,
            basis=ObservationBasis.COUNTED,
        ),
        time(day),
        time(day),
    )


def amount(bounds) -> str:
    low = "unbounded" if bounds.minimum is None else str(bounds.minimum)
    high = "unbounded" if bounds.maximum is None else str(bounds.maximum)
    return low if low == high else f"{low}..{high}"


def show(title: str, timeline: ProcessQuantityTimeline, holdings=()):
    compiled = timeline.compile()
    print(f"\n=== {title} ===")
    print("Replay order: " + " -> ".join(compiled.event_order))
    print("Generated relationships:")
    for relation in compiled.rendered_constraints():
        print(f"  {relation}")
    print("Result:")
    if not compiled.is_feasible():
        print("  CONFLICT: " + ", ".join(compiled.conflict()))
    for label, holding in holdings:
        try:
            rendered = amount(compiled.current_bounds(holding))
        except InfeasibleQuantityFacts:
            rendered = "no feasible quantity"
        print(f"  {label}: {rendered} {holding.unit}")
    return compiled


def move_trace():
    source = HoldingKey("BAT-SCREW", "BIN-A", "each")
    destination = HoldingKey("BAT-SCREW", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact("OBS-ten", source, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-move-three",
        "move",
        time(2),
        time(2),
        inputs=(ProcessInput("moved", (source,), ExactAmount(3)),),
        outputs=(ProcessOutput(
            "destination", destination, DISCRETE, FromInput("moved")
        ),),
    ))
    show(
        "Move consumes only the participating quantity",
        timeline,
        (("source remainder (derived)", source), ("destination", destination)),
    )


def ambiguous_trace():
    first = HoldingKey("BAT-A", "BIN-SHARED", "each")
    second = HoldingKey("BAT-B", "BIN-SHARED", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact("OBS-A-ten", first, 10, 1))
    timeline.record(exact("OBS-B-ten", second, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-take-five",
        "consume",
        time(2),
        time(2),
        inputs=(ProcessInput(
            "fasteners",
            (first, second),
            ExactAmount(5),
            selector="SKU-FASTENER observed in BIN-SHARED",
        ),),
        sinks=(ProcessSink(
            "project",
            "consumed by project",
            "each",
            DISCRETE,
            FromInput("fasteners"),
        ),),
    ))
    compiled = show(
        "Same SKU and Bin, source Batch unknown",
        timeline,
        (("Batch A", first), ("Batch B", second)),
    )
    print(
        "  combined remainder: "
        f"{amount(compiled.current_total_bounds((first, second)))} each"
    )
    print(
        "  possible draw from Batch A: "
        f"{amount(compiled.allocation_bounds('PROC-take-five', 'fasteners', first))} each"
    )
    print(
        "  possible draw from Batch B: "
        f"{amount(compiled.allocation_bounds('PROC-take-five', 'fasteners', second))} each"
    )


def audit_trace():
    holding = HoldingKey("BAT-BOLTS", "BIN-AUDIT", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(ObservationEvent(
        holding,
        DISCRETE,
        QuantityObservation(
            "OBS-saw-ten",
            lower=10,
            basis=ObservationBasis.COUNTED,
        ),
        time(1),
        time(1),
    ))
    show("Audit: saw at least ten", timeline, (("bolts", holding),))
    timeline.record(ObservationEvent(
        holding,
        DISCRETE,
        QuantityObservation(
            "OBS-capacity-forty",
            upper=40,
            basis=ObservationBasis.MEASURED,
        ),
        time(2),
        time(2),
    ))
    show("Audit: later upper bound", timeline, (("bolts", holding),))
    timeline.record(exact("OBS-complete-count", holding, 25, 3))
    show("Audit: complete count", timeline, (("bolts", holding),))


def reclassification_trace():
    old = HoldingKey("BAT-WRONG", "BIN-PARTS", "each")
    new = HoldingKey("BAT-CORRECT", "BIN-PARTS", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(ObservationEvent(
        old,
        DISCRETE,
        QuantityObservation(
            "OBS-old-estimate",
            lower=8,
            preferred=10,
            upper=12,
            basis=ObservationBasis.ESTIMATED,
        ),
        time(1),
        time(1),
    ))
    timeline.record(ProcessEvent(
        "PROC-reclassify",
        "reclassify",
        time(2),
        time(2),
        inputs=(ProcessInput("old-batch", (old,), ALL_REMAINING),),
        outputs=(ProcessOutput(
            "new-batch", new, DISCRETE, FromInput("old-batch")
        ),),
    ))
    show(
        "Whole-Batch reclassification",
        timeline,
        (("old Batch", old), ("new Batch", new)),
    )


def assembly_trace():
    screws = HoldingKey("BAT-SCREWS", "BIN-SCREWS", "each")
    body = HoldingKey("BAT-BODY", "BIN-BODIES", "each")
    machine = HoldingKey("BAT-MACHINE", "BENCH", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact("OBS-screws-twenty", screws, 20, 1))
    timeline.record(exact("OBS-one-body", body, 1, 1))
    timeline.record(ProcessEvent(
        "PROC-assemble",
        "assembly",
        time(2),
        time(2),
        inputs=(
            ProcessInput(
                "fasteners",
                (screws,),
                ExactAmount(4),
                "fasteners",
                contributes_to=("machine",),
            ),
            ProcessInput(
                "body",
                (body,),
                ExactAmount(1),
                "machine body",
                contributes_to=("machine",),
            ),
        ),
        outputs=(ProcessOutput(
            "machine",
            machine,
            DISCRETE,
            ExactAmount(1),
            "assembled machine",
        ),),
    ))
    show(
        "Assembly uses ordinary inputs and outputs",
        timeline,
        (("unused screws", screws), ("unused bodies", body), ("machine", machine)),
    )


def late_conflict_trace():
    source = HoldingKey("BAT-LATE", "BIN-A", "each")
    moved = HoldingKey("BAT-LATE", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact("OBS-opening-ten", source, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-move-six",
        "move",
        time(3),
        time(3),
        inputs=(ProcessInput("moved", (source,), ExactAmount(6)),),
        outputs=(ProcessOutput(
            "destination", moved, DISCRETE, FromInput("moved")
        ),),
    ))
    timeline.record(exact("OBS-four-remain", source, 4, 4))
    show("History before late recording", timeline, (("source", source),))
    timeline.record(ProcessEvent(
        "PROC-late-five",
        "consume",
        time(2),
        time(5),
        inputs=(ProcessInput("consumed", (source,), ExactAmount(5)),),
        sinks=(ProcessSink(
            "unknown-use",
            "late-recorded consumption",
            "each",
            DISCRETE,
            FromInput("consumed"),
        ),),
    ))
    show(
        "Late process inserted before later events",
        timeline,
        (("source", source), ("moved destination", moved)),
    )


def main():
    move_trace()
    ambiguous_trace()
    audit_trace()
    reclassification_trace()
    assembly_trace()
    late_conflict_trace()


if __name__ == "__main__":
    main()
