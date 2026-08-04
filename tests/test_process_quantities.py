"""Executable scenarios for the process-oriented quantity compiler."""

from datetime import datetime, timezone
from fractions import Fraction

import pytest

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


def moment(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=timezone.utc)


def observation(
    event_id: str,
    holding: HoldingKey,
    claim: QuantityObservation,
    day: int,
    recorded_day: int | None = None,
) -> ObservationEvent:
    assert event_id == claim.observation_id
    return ObservationEvent(
        holding,
        DISCRETE,
        claim,
        moment(day),
        moment(day if recorded_day is None else recorded_day),
    )


def exact_observation(
    event_id: str,
    holding: HoldingKey,
    amount: int,
    day: int,
    recorded_day: int | None = None,
) -> ObservationEvent:
    return observation(
        event_id,
        holding,
        QuantityObservation.exact(
            event_id,
            amount,
            basis=ObservationBasis.COUNTED,
        ),
        day,
        recorded_day,
    )


def assert_bounds(bounds, minimum, maximum):
    assert bounds.minimum == (
        None if minimum is None else Fraction(str(minimum))
    )
    assert bounds.maximum == (
        None if maximum is None else Fraction(str(maximum))
    )


def test_move_consumes_only_the_selected_amount_and_derives_the_remainder():
    source = HoldingKey("BAT-SCREW", "BIN-A", "each")
    destination = HoldingKey("BAT-SCREW", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-ten", source, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-move-three",
        "move",
        moment(2),
        moment(2),
        inputs=(ProcessInput("moved", (source,), ExactAmount(3)),),
        outputs=(ProcessOutput(
            "destination",
            destination,
            DISCRETE,
            FromInput("moved"),
        ),),
    ))

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(source), 7, 7)
    assert_bounds(compiled.current_bounds(destination), 3, 3)
    rendered = "\n".join(compiled.rendered_constraints())
    assert "PROC-move-three:moved:source" in rendered
    assert "PROC-move-three:destination:destination" in rendered
    assert "remainder" not in rendered


def test_same_sku_same_bin_preserves_unknown_batch_allocation():
    first = HoldingKey("BAT-A", "BIN-SHARED", "each")
    second = HoldingKey("BAT-B", "BIN-SHARED", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-A-ten", first, 10, 1))
    timeline.record(exact_observation("OBS-B-ten", second, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-take-five",
        "consume",
        moment(2),
        moment(2),
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

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(first), 5, 10)
    assert_bounds(compiled.current_bounds(second), 5, 10)
    assert_bounds(compiled.current_total_bounds((first, second)), 15, 15)
    assert_bounds(
        compiled.allocation_bounds("PROC-take-five", "fasteners", first),
        0,
        5,
    )
    assert_bounds(
        compiled.allocation_bounds("PROC-take-five", "fasteners", second),
        0,
        5,
    )


def test_audit_constraints_can_assert_lower_upper_or_complete_count():
    holding = HoldingKey("BAT-BOLTS", "BIN-AUDIT", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(observation(
        "OBS-saw-ten",
        holding,
        QuantityObservation(
            "OBS-saw-ten",
            lower=10,
            basis=ObservationBasis.COUNTED,
        ),
        1,
    ))
    lower_only = timeline.compile()
    assert_bounds(lower_only.current_bounds(holding), 10, None)

    timeline.record(observation(
        "OBS-container-at-most-forty",
        holding,
        QuantityObservation(
            "OBS-container-at-most-forty",
            upper=40,
            basis=ObservationBasis.MEASURED,
        ),
        2,
    ))
    bounded = timeline.compile()
    assert_bounds(bounded.current_bounds(holding), 10, 40)

    timeline.record(exact_observation("OBS-complete-count", holding, 25, 3))
    exact = timeline.compile()
    assert_bounds(exact.current_bounds(holding), 25, 25)


def test_whole_batch_reclassification_consumes_identity_not_a_remainder():
    old = HoldingKey("BAT-WRONG", "BIN-PARTS", "each")
    new = HoldingKey("BAT-CORRECT", "BIN-PARTS", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(observation(
        "OBS-old-estimate",
        old,
        QuantityObservation(
            "OBS-old-estimate",
            lower=8,
            preferred=10,
            upper=12,
            basis=ObservationBasis.ESTIMATED,
        ),
        1,
    ))
    timeline.record(ProcessEvent(
        "PROC-reclassify",
        "reclassify",
        moment(2),
        moment(2),
        inputs=(ProcessInput("old-batch", (old,), ALL_REMAINING),),
        outputs=(ProcessOutput(
            "new-batch",
            new,
            DISCRETE,
            FromInput("old-batch"),
        ),),
    ))

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(old), 0, 0)
    assert_bounds(compiled.current_bounds(new), 8, 12)
    assert_bounds(compiled.input_bounds("PROC-reclassify", "old-batch"), 8, 12)


def test_assembly_is_a_normal_process_without_adding_incompatible_units():
    screws = HoldingKey("BAT-SCREWS", "BIN-SCREWS", "each")
    body = HoldingKey("BAT-BODY", "BIN-BODIES", "each")
    machine = HoldingKey("BAT-MACHINE", "BENCH", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-screws", screws, 20, 1))
    timeline.record(exact_observation("OBS-body", body, 1, 1))
    timeline.record(ProcessEvent(
        "PROC-assemble",
        "assembly",
        moment(2),
        moment(2),
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

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(screws), 16, 16)
    assert_bounds(compiled.current_bounds(body), 0, 0)
    assert_bounds(compiled.current_bounds(machine), 1, 1)


def test_late_process_replays_by_occurrence_time_and_can_break_future_history():
    source = HoldingKey("BAT-LATE", "BIN-A", "each")
    moved = HoldingKey("BAT-LATE", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-opening-ten", source, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-move-six",
        "move",
        moment(3),
        moment(3),
        inputs=(ProcessInput("moved", (source,), ExactAmount(6)),),
        outputs=(ProcessOutput(
            "destination",
            moved,
            DISCRETE,
            FromInput("moved"),
        ),),
    ))
    timeline.record(exact_observation("OBS-four-remain", source, 4, 4))

    before_late_record = timeline.compile(known_at=moment(4, 13))
    assert before_late_record.is_feasible()
    assert_bounds(before_late_record.current_bounds(source), 4, 4)

    timeline.record(ProcessEvent(
        "PROC-late-five",
        "consume",
        moment(2),
        moment(5),
        inputs=(ProcessInput("consumed", (source,), ExactAmount(5)),),
        sinks=(ProcessSink(
            "unknown-use",
            "late-recorded consumption",
            "each",
            DISCRETE,
            FromInput("consumed"),
        ),),
        note="Recorded three days after it occurred",
    ))

    after_late_record = timeline.compile(known_at=moment(5, 13))
    assert after_late_record.event_order == (
        "OBS-opening-ten",
        "PROC-late-five",
        "PROC-move-six",
        "OBS-four-remain",
    )
    assert not after_late_record.is_feasible()
    assert "PROC-late-five:consumed:source" in after_late_record.conflict()
    with pytest.raises(InfeasibleQuantityFacts):
        after_late_record.current_bounds(source)


def test_process_validation_stops_undefined_same_holding_semantics():
    holding = HoldingKey("BAT-X", "BIN-X", "each")
    with pytest.raises(ValueError, match="same-holding"):
        ProcessEvent(
            "PROC-undefined",
            "undefined",
            moment(1),
            moment(1),
            inputs=(ProcessInput("input", (holding,), ExactAmount(1)),),
            outputs=(ProcessOutput(
                "output",
                holding,
                DISCRETE,
                FromInput("input"),
            ),),
        )


def test_process_input_cannot_be_a_meaningless_withdrawal():
    holding = HoldingKey("BAT-X", "BIN-X", "each")
    with pytest.raises(ValueError, match="output, sink, or structural"):
        ProcessEvent(
            "PROC-bare-withdrawal",
            "use",
            moment(1),
            moment(1),
            inputs=(ProcessInput("input", (holding,), ExactAmount(1)),),
        )


def test_output_only_process_waits_for_explicit_external_source_semantics():
    holding = HoldingKey("BAT-X", "BIN-X", "each")
    with pytest.raises(ValueError, match="external-source"):
        ProcessEvent(
            "PROC-anonymous-creation",
            "receive",
            moment(1),
            moment(1),
            outputs=(ProcessOutput(
                "received",
                holding,
                DISCRETE,
                ExactAmount(1),
            ),),
        )


def test_ambiguous_input_cannot_collapse_into_one_concrete_batch():
    first = HoldingKey("BAT-A", "BIN-A", "each")
    second = HoldingKey("BAT-B", "BIN-A", "each")
    output = HoldingKey("BAT-A", "BIN-B", "each")
    with pytest.raises(ValueError, match="ambiguous input"):
        ProcessEvent(
            "PROC-ambiguous-move",
            "move",
            moment(1),
            moment(1),
            inputs=(ProcessInput(
                "moved",
                (first, second),
                ExactAmount(1),
                selector="SKU-X in BIN-A",
            ),),
            outputs=(ProcessOutput(
                "destination",
                output,
                DISCRETE,
                FromInput("moved"),
            ),),
        )
