#!/usr/bin/env python3
"""Print concrete process/observation traces from the experimental compiler."""

from datetime import datetime, timezone

from inventorius.ledger import HoldingKey
from inventorius.process_quantities import (
    BatchReplacement,
    CandidateSelection,
    DeclaredOneToOneTransformation,
    ExactAmount,
    FromInput,
    FromSource,
    ObservationEvent,
    OneToOneTransformedFromInput,
    PreservedIdentityOutput,
    ProcessEvent,
    ProcessInput,
    ProcessOutput,
    ProcessQuantityTimeline,
    ProcessSink,
    ProcessSource,
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


def selection(selection_id, sku_id, location_id, *candidates):
    return CandidateSelection(
        selection_id,
        sku_id,
        location_id,
        candidates[0].unit,
        candidates[0].packaging_configuration_id,
    )


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
            selector=selection(
                "SEL-fasteners",
                "SKU-FASTENER",
                "BIN-SHARED",
                first,
                second,
            ),
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


def ambiguous_move_trace():
    first_source = HoldingKey("BAT-A", "BIN-A", "each")
    second_source = HoldingKey("BAT-B", "BIN-A", "each")
    first_destination = HoldingKey("BAT-A", "BIN-B", "each")
    second_destination = HoldingKey("BAT-B", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact("OBS-A-ten-move", first_source, 10, 1))
    timeline.record(exact("OBS-B-ten-move", second_source, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-ambiguous-move",
        "move",
        time(2),
        time(2),
        inputs=(ProcessInput(
            "moved",
            (first_source, second_source),
            ExactAmount(5),
            selector=selection(
                "SEL-move-fasteners",
                "SKU-FASTENER",
                "BIN-A",
                first_source,
                second_source,
            ),
        ),),
        preserved_outputs=(PreservedIdentityOutput(
            "destination",
            "moved",
            "BIN-B",
        ),),
    ))
    compiled = show(
        "Ambiguous move preserves possible Batch identities",
        timeline,
        (
            ("Batch A source", first_source),
            ("Batch B source", second_source),
            ("Batch A destination", first_destination),
            ("Batch B destination", second_destination),
        ),
    )
    destination_total = compiled.current_total_bounds(
        (first_destination, second_destination)
    )
    print(f"  combined destination: {amount(destination_total)} each")


def ambiguous_transformation_trace():
    first = HoldingKey("BAT-A", "BIN-SHARED", "each")
    second = HoldingKey("BAT-B", "BIN-SHARED", "each")
    transformed = HoldingKey("BAT-C", "BIN-OUTPUT", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact("OBS-A-ten-transform", first, 10, 1))
    timeline.record(exact("OBS-B-ten-transform", second, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-transform-five",
        "one-to-one transformation",
        time(2),
        time(2),
        inputs=(ProcessInput(
            "unprocessed",
            (first, second),
            ExactAmount(5),
            selector=selection(
                "SEL-unprocessed",
                "SKU-UNPROCESSED",
                "BIN-SHARED",
                first,
                second,
            ),
        ),),
        outputs=(ProcessOutput(
            "processed",
            transformed,
            DISCRETE,
            OneToOneTransformedFromInput(
                "unprocessed",
                DeclaredOneToOneTransformation(
                    "SKU-UNPROCESSED",
                    "SKU-PROCESSED",
                    "each",
                    DISCRETE,
                ),
            ),
        ),),
    ))
    compiled = show(
        "Ambiguous sources form one new Batch without losing correlation",
        timeline,
        (
            ("Batch A remainder", first),
            ("Batch B remainder", second),
            ("new Batch C", transformed),
        ),
    )
    for label, holding in (("Batch A", first), ("Batch B", second)):
        source_allocation = compiled.output_source_allocation_bounds(
            "PROC-transform-five",
            "processed",
            holding,
        )
        print(
            f"  possible source allocation from {label}: "
            f"{amount(source_allocation)} each"
        )
    combined = compiled.output_source_allocation_total_bounds(
        "PROC-transform-five",
        "processed",
        (first, second),
    )
    print(f"  combined source allocation: {amount(combined)} each")

    timeline.record(exact("OBS-A-seven-remain", first, 7, 3))
    tightened = show(
        "A later audit tightens the earlier transformation",
        timeline,
        (("Batch A remainder", first), ("Batch B remainder", second)),
    )
    for label, holding in (("Batch A", first), ("Batch B", second)):
        source_allocation = tightened.output_source_allocation_bounds(
            "PROC-transform-five",
            "processed",
            holding,
        )
        print(
            f"  proven source allocation from {label}: "
            f"{amount(source_allocation)} each"
        )


def reclassification_trace():
    old = HoldingKey("BAT-WRONG", "BIN-PARTS", "each")
    old_bench = HoldingKey("BAT-WRONG", "BENCH", "each")
    new = HoldingKey("BAT-CORRECT", "BIN-PARTS", "each")
    new_bench = HoldingKey("BAT-CORRECT", "BENCH", "each")
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
    timeline.record(exact("OBS-old-bench", old_bench, 3, 1))
    timeline.record(ProcessEvent(
        "PROC-reclassify",
        "reclassify",
        time(2),
        time(2),
        batch_replacements=(BatchReplacement(
            "replace-identity",
            "BAT-WRONG",
            "BAT-CORRECT",
        ),),
    ))
    show(
        "Whole-Batch reclassification",
        timeline,
        (
            ("old Batch in bin", old),
            ("old Batch on bench", old_bench),
            ("new Batch in bin", new),
            ("new Batch on bench", new_bench),
        ),
    )


def receive_trace():
    holding = HoldingKey("BAT-LIQUID", "SHELF", "milliliter")
    timeline = ProcessQuantityTimeline()
    timeline.record(ProcessEvent(
        "PROC-receive-liquid",
        "receive",
        time(1),
        time(1),
        sources=(ProcessSource(
            "supplier-bottle",
            "supplier shipment",
            "milliliter",
            QuantityDomain.CONTINUOUS,
            QuantityObservation.estimated("OBS-bottle-estimate", 50),
        ),),
        outputs=(ProcessOutput(
            "received-bottle",
            holding,
            QuantityDomain.CONTINUOUS,
            FromSource("supplier-bottle"),
        ),),
    ))
    show(
        "Receive crosses an explicit external boundary",
        timeline,
        (("received liquid", holding),),
    )


def late_candidate_trace():
    first = HoldingKey("BAT-A", "BIN-SHARED", "each")
    second = HoldingKey("BAT-B", "BIN-SHARED", "each")
    late = HoldingKey("BAT-C", "BIN-SHARED", "each")
    selector = selection(
        "SEL-shared-fasteners",
        "SKU-FASTENER",
        "BIN-SHARED",
        first,
        second,
    )
    timeline = ProcessQuantityTimeline()
    timeline.record(exact("OBS-A-two", first, 2, 1))
    timeline.record(exact("OBS-B-two", second, 2, 1))
    timeline.record(ObservationEvent(
        late,
        DISCRETE,
        QuantityObservation.exact(
            "OBS-C-two-recorded-late",
            2,
            basis=ObservationBasis.COUNTED,
        ),
        time(1),
        time(3),
    ))
    timeline.record(ProcessEvent(
        "PROC-take-three",
        "consume",
        time(2),
        time(2),
        inputs=(ProcessInput(
            "fasteners",
            (first, second),
            ExactAmount(3),
            selector=selector,
        ),),
        sinks=(ProcessSink(
            "project",
            "consumed by project",
            "each",
            DISCRETE,
            FromInput("fasteners"),
        ),),
    ))

    def resolve(
        candidate_selection,
        candidates_at_recording,
        occurred_at,
        known_at,
    ):
        return (first, second, late) if known_at is None else (first, second)

    historical = timeline.compile(
        known_at=time(2, 13),
        candidate_resolver=resolve,
    )
    current = timeline.compile(candidate_resolver=resolve)
    print("\n=== Late Batch discovery changes possibilities, not the observation ===")
    print(
        "  historical candidate remainder: "
        f"{amount(historical.current_total_bounds((first, second)))} each"
    )
    print(
        "  current candidate remainder: "
        f"{amount(current.current_total_bounds((first, second, late)))} each"
    )
    for label, holding in (("Batch A", first), ("Batch B", second), ("Batch C", late)):
        print(
            f"  current possible draw from {label}: "
            f"{amount(current.allocation_bounds('PROC-take-three', 'fasteners', holding))} each"
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
                structurally_contributes_to=("machine",),
            ),
            ProcessInput(
                "body",
                (body,),
                ExactAmount(1),
                "machine body",
                structurally_contributes_to=("machine",),
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
    ambiguous_move_trace()
    ambiguous_transformation_trace()
    audit_trace()
    receive_trace()
    reclassification_trace()
    late_candidate_trace()
    assembly_trace()
    late_conflict_trace()


if __name__ == "__main__":
    main()
