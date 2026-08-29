"""Executable scenarios for the process-oriented quantity compiler."""

from datetime import datetime, timezone
from fractions import Fraction

import pytest

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


def selection(
    selection_id: str,
    sku_id: str,
    location_id: str,
    *candidates: HoldingKey,
) -> CandidateSelection:
    return CandidateSelection(
        selection_id,
        sku_id,
        location_id,
        candidates[0].unit,
        candidates[0].packaging_configuration_id,
    )


def declared_one_to_one_transformation(
    source_sku_id: str,
    output_sku_id: str,
) -> DeclaredOneToOneTransformation:
    return DeclaredOneToOneTransformation(
        source_sku_id,
        output_sku_id,
        "each",
        DISCRETE,
    )


def ambiguous_transformation_timeline(
    first_amount: int = 10,
    second_amount: int = 10,
    process_id: str = "PROC-transform-five",
):
    first = HoldingKey("BAT-A", "BIN-SHARED", "each")
    second = HoldingKey("BAT-B", "BIN-SHARED", "each")
    transformed = HoldingKey("BAT-C", "BIN-OUTPUT", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation(
        "OBS-A-opening",
        first,
        first_amount,
        1,
    ))
    timeline.record(exact_observation(
        "OBS-B-opening",
        second,
        second_amount,
        1,
    ))
    timeline.record(ProcessEvent(
        process_id,
        "one-to-one transformation",
        moment(2),
        moment(2),
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
                declared_one_to_one_transformation(
                    "SKU-UNPROCESSED",
                    "SKU-PROCESSED",
                ),
            ),
        ),),
    ))
    return timeline, first, second, transformed


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


def test_whole_batch_reclassification_expands_across_every_current_holding():
    old_first = HoldingKey("BAT-WRONG", "BIN-PARTS", "each")
    old_second = HoldingKey("BAT-WRONG", "BENCH", "each")
    new_first = HoldingKey("BAT-CORRECT", "BIN-PARTS", "each")
    new_second = HoldingKey("BAT-CORRECT", "BENCH", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(observation(
        "OBS-old-first-estimate",
        old_first,
        QuantityObservation(
            "OBS-old-first-estimate",
            lower=8,
            preferred=10,
            upper=12,
            basis=ObservationBasis.ESTIMATED,
        ),
        1,
    ))
    timeline.record(exact_observation(
        "OBS-old-second-three",
        old_second,
        3,
        1,
    ))
    timeline.record(ProcessEvent(
        "PROC-reclassify",
        "reclassify",
        moment(2),
        moment(2),
        batch_replacements=(BatchReplacement(
            "replace-identity",
            "BAT-WRONG",
            "BAT-CORRECT",
        ),),
    ))

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(old_first), 0, 0)
    assert_bounds(compiled.current_bounds(old_second), 0, 0)
    assert_bounds(compiled.current_bounds(new_first), 8, 12)
    assert_bounds(compiled.current_bounds(new_second), 3, 3)
    assert compiled.replacement_holdings("PROC-reclassify") == (
        (old_second, new_second),
        (old_first, new_first),
    )


def test_late_discovered_holding_joins_batch_replacement_on_current_replay():
    known = HoldingKey("BAT-WRONG", "BIN-A", "each")
    discovered_late = HoldingKey("BAT-WRONG", "BIN-B", "each")
    corrected_known = HoldingKey("BAT-CORRECT", "BIN-A", "each")
    corrected_late = HoldingKey("BAT-CORRECT", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-known", known, 2, 1))
    timeline.record(exact_observation(
        "OBS-discovered-late",
        discovered_late,
        4,
        1,
        recorded_day=3,
    ))
    timeline.record(ProcessEvent(
        "PROC-reclassify",
        "reclassify",
        moment(2),
        moment(2),
        batch_replacements=(BatchReplacement(
            "replace-identity",
            "BAT-WRONG",
            "BAT-CORRECT",
        ),),
    ))

    historical = timeline.compile(known_at=moment(2, 13))
    assert historical.replacement_holdings("PROC-reclassify") == (
        (known, corrected_known),
    )

    current = timeline.compile()
    assert current.replacement_holdings("PROC-reclassify") == (
        (known, corrected_known),
        (discovered_late, corrected_late),
    )
    assert_bounds(current.current_bounds(discovered_late), 0, 0)
    assert_bounds(current.current_bounds(corrected_late), 4, 4)


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


def test_process_input_cannot_feed_two_concrete_outputs_in_full():
    source = HoldingKey("BAT-X", "BIN-A", "each")
    first_output = HoldingKey("BAT-X", "BIN-B", "each")
    second_output = HoldingKey("BAT-X", "BIN-C", "each")

    with pytest.raises(ValueError, match="multiple quantity destinations"):
        ProcessEvent(
            "PROC-duplicate-output",
            "invalid split",
            moment(1),
            moment(1),
            inputs=(ProcessInput("input", (source,), ExactAmount(5)),),
            outputs=(
                ProcessOutput(
                    "first",
                    first_output,
                    DISCRETE,
                    FromInput("input"),
                ),
                ProcessOutput(
                    "second",
                    second_output,
                    DISCRETE,
                    FromInput("input"),
                ),
            ),
        )


def test_process_input_cannot_feed_an_output_and_sink_in_full():
    source = HoldingKey("BAT-X", "BIN-A", "each")
    output = HoldingKey("BAT-X", "BIN-B", "each")

    with pytest.raises(ValueError, match="multiple quantity destinations"):
        ProcessEvent(
            "PROC-output-and-sink",
            "invalid split",
            moment(1),
            moment(1),
            inputs=(ProcessInput("input", (source,), ExactAmount(5)),),
            outputs=(ProcessOutput(
                "output",
                output,
                DISCRETE,
                FromInput("input"),
            ),),
            sinks=(ProcessSink(
                "sink",
                "also consumed",
                "each",
                DISCRETE,
                FromInput("input"),
            ),),
        )


def test_process_input_cannot_feed_two_preserved_outputs_in_full():
    first = HoldingKey("BAT-A", "BIN-A", "each")
    second = HoldingKey("BAT-B", "BIN-A", "each")

    with pytest.raises(ValueError, match="multiple quantity destinations"):
        ProcessEvent(
            "PROC-two-preserved-outputs",
            "invalid split",
            moment(1),
            moment(1),
            inputs=(ProcessInput(
                "input",
                (first, second),
                ExactAmount(5),
                selector=selection(
                    "SEL-X",
                    "SKU-X",
                    "BIN-A",
                    first,
                    second,
                ),
            ),),
            preserved_outputs=(
                PreservedIdentityOutput("first", "input", "BIN-B"),
                PreservedIdentityOutput("second", "input", "BIN-C"),
            ),
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


def test_inputless_process_cannot_create_an_output_unlinked_to_its_source():
    received = HoldingKey("BAT-RECEIVED", "SHELF", "each")
    unlinked = HoldingKey("BAT-UNLINKED", "SHELF", "each")

    with pytest.raises(ValueError, match="every output.*external source"):
        ProcessEvent(
            "PROC-invalid-receipt",
            "receive",
            moment(1),
            moment(1),
            sources=(ProcessSource(
                "shipment",
                "supplier shipment",
                "each",
                DISCRETE,
                QuantityObservation.exact(
                    "OBS-shipment",
                    1,
                    basis=ObservationBasis.COUNTED,
                ),
            ),),
            outputs=(
                ProcessOutput(
                    "received",
                    received,
                    DISCRETE,
                    FromSource("shipment"),
                ),
                ProcessOutput(
                    "unlinked",
                    unlinked,
                    DISCRETE,
                    ExactAmount(100),
                ),
            ),
        )


def test_receive_uses_an_explicit_bounded_external_source():
    holding = HoldingKey("BAT-LIQUID", "SHELF", "milliliter")
    timeline = ProcessQuantityTimeline()
    timeline.record(ProcessEvent(
        "PROC-receive-liquid",
        "receive",
        moment(1),
        moment(1),
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

    compiled = timeline.compile()

    assert_bounds(compiled.source_bounds(
        "PROC-receive-liquid",
        "supplier-bottle",
    ), 0, 100)
    assert_bounds(compiled.current_bounds(holding), 0, 100)


def test_state_ids_distinguish_absent_and_literal_dash_package_ids():
    unpackaged = HoldingKey("BAT-X", "SHELF", "each")
    literal_dash_package = HoldingKey("BAT-X", "SHELF", "each", "-")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-unpackaged", unpackaged, 3, 1))
    timeline.record(exact_observation(
        "OBS-literal-dash-package",
        literal_dash_package,
        7,
        1,
    ))

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(unpackaged), 3, 3)
    assert_bounds(compiled.current_bounds(literal_dash_package), 7, 7)


def test_equal_time_overlap_requires_explicit_effective_order():
    source = HoldingKey("BAT-X", "BIN-A", "each")
    destination = HoldingKey("BAT-X", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-opening", source, 3, 1))
    timeline.record(ProcessEvent(
        "PROC-move-one",
        "move",
        moment(1),
        moment(1),
        inputs=(ProcessInput("moved", (source,), ExactAmount(1)),),
        outputs=(ProcessOutput(
            "destination",
            destination,
            DISCRETE,
            FromInput("moved"),
        ),),
    ))

    with pytest.raises(ValueError, match="effective_order"):
        timeline.compile()

    ordered = ProcessQuantityTimeline()
    ordered.record(exact_observation("OBS-opening", source, 3, 1))
    ordered.record(ProcessEvent(
        "PROC-move-one",
        "move",
        moment(1),
        moment(1),
        inputs=(ProcessInput("moved", (source,), ExactAmount(1)),),
        outputs=(ProcessOutput(
            "destination",
            destination,
            DISCRETE,
            FromInput("moved"),
        ),),
        effective_order=1,
    ))
    compiled = ordered.compile()
    assert_bounds(compiled.current_bounds(source), 2, 2)
    assert_bounds(compiled.current_bounds(destination), 1, 1)


@pytest.mark.parametrize("batch_id", ("BAT-WRONG", "BAT-CORRECT"))
@pytest.mark.parametrize("replacement_process_id", ("AAA-replace", "ZZZ-replace"))
def test_same_time_new_observation_overlaps_whole_batch_replacement(
    batch_id,
    replacement_process_id,
):
    observed = HoldingKey(batch_id, "BIN-NEW", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("MMM-observation", observed, 3, 1))
    timeline.record(ProcessEvent(
        replacement_process_id,
        "reclassify",
        moment(1),
        moment(1),
        batch_replacements=(BatchReplacement(
            "replace-identity",
            "BAT-WRONG",
            "BAT-CORRECT",
        ),),
    ))

    with pytest.raises(ValueError, match="effective_order"):
        timeline.compile()


@pytest.mark.parametrize("batch_id", ("BAT-WRONG", "BAT-CORRECT"))
@pytest.mark.parametrize("producer_process_id", ("AAA-produce", "ZZZ-produce"))
def test_same_time_new_output_overlaps_whole_batch_replacement(
    batch_id,
    producer_process_id,
):
    produced = HoldingKey(batch_id, "BIN-NEW", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(ProcessEvent(
        producer_process_id,
        "receive",
        moment(1),
        moment(1),
        sources=(ProcessSource(
            "supplier",
            "supplier",
            "each",
            DISCRETE,
            QuantityObservation.exact(
                "OBS-received",
                3,
                basis=ObservationBasis.COUNTED,
            ),
        ),),
        outputs=(ProcessOutput(
            "received",
            produced,
            DISCRETE,
            FromSource("supplier"),
        ),),
    ))
    timeline.record(ProcessEvent(
        "MMM-replace",
        "reclassify",
        moment(1),
        moment(1),
        batch_replacements=(BatchReplacement(
            "replace-identity",
            "BAT-WRONG",
            "BAT-CORRECT",
        ),),
    ))

    with pytest.raises(ValueError, match="effective_order"):
        timeline.compile()


def test_same_time_overlapping_batch_replacements_need_explicit_order():
    timeline = ProcessQuantityTimeline()
    timeline.record(ProcessEvent(
        "PROC-first-replacement",
        "reclassify",
        moment(1),
        moment(1),
        batch_replacements=(BatchReplacement(
            "replace-a-with-b",
            "BAT-A",
            "BAT-B",
        ),),
    ))
    timeline.record(ProcessEvent(
        "PROC-second-replacement",
        "reclassify",
        moment(1),
        moment(1),
        batch_replacements=(BatchReplacement(
            "replace-b-with-c",
            "BAT-B",
            "BAT-C",
        ),),
    ))

    with pytest.raises(ValueError, match="effective_order"):
        timeline.compile()


def test_explicit_order_allows_observation_before_whole_batch_replacement():
    old = HoldingKey("BAT-WRONG", "BIN-NEW", "each")
    corrected = HoldingKey("BAT-CORRECT", "BIN-NEW", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-opening", old, 3, 1))
    timeline.record(ProcessEvent(
        "PROC-replace",
        "reclassify",
        moment(1),
        moment(1),
        batch_replacements=(BatchReplacement(
            "replace-identity",
            "BAT-WRONG",
            "BAT-CORRECT",
        ),),
        effective_order=1,
    ))

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(old), 0, 0)
    assert_bounds(compiled.current_bounds(corrected), 3, 3)


def test_ambiguous_selection_can_gain_a_late_discovered_candidate():
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
    timeline.record(exact_observation("OBS-A-two", first, 2, 1))
    timeline.record(exact_observation("OBS-B-two", second, 2, 1))
    timeline.record(exact_observation("OBS-C-two-late", late, 2, 1, 3))
    timeline.record(ProcessEvent(
        "PROC-take-three",
        "consume",
        moment(2),
        moment(2),
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
        assert candidate_selection == selector
        assert candidates_at_recording == (first, second)
        assert occurred_at == moment(2)
        return (first, second, late) if known_at is None else (first, second)

    historical = timeline.compile(
        known_at=moment(2, 13),
        candidate_resolver=resolve,
    )
    assert_bounds(historical.current_total_bounds((first, second)), 1, 1)
    with pytest.raises(ValueError, match="no allocation"):
        historical.allocation_bounds(
            "PROC-take-three",
            "fasteners",
            late,
        )

    current = timeline.compile(candidate_resolver=resolve)
    assert_bounds(current.current_total_bounds((first, second, late)), 3, 3)
    assert_bounds(current.allocation_bounds(
        "PROC-take-three",
        "fasteners",
        late,
    ), 0, 2)


def test_resolver_cannot_make_two_inputs_consume_the_same_holding():
    first = HoldingKey("BAT-A", "BIN-SHARED", "each")
    second = HoldingKey("BAT-B", "BIN-SHARED", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-A-two", first, 2, 1))
    timeline.record(exact_observation("OBS-B-two", second, 2, 1))
    timeline.record(ProcessEvent(
        "PROC-consume-two-legs",
        "consume",
        moment(2),
        moment(2),
        inputs=(
            ProcessInput(
                "first-leg",
                (first,),
                ExactAmount(1),
                selector=selection(
                    "SEL-first",
                    "SKU-X",
                    "BIN-SHARED",
                    first,
                ),
            ),
            ProcessInput(
                "second-leg",
                (second,),
                ExactAmount(1),
                selector=selection(
                    "SEL-second",
                    "SKU-X",
                    "BIN-SHARED",
                    second,
                ),
            ),
        ),
        sinks=(
            ProcessSink(
                "first-use",
                "consumed",
                "each",
                DISCRETE,
                FromInput("first-leg"),
            ),
            ProcessSink(
                "second-use",
                "consumed",
                "each",
                DISCRETE,
                FromInput("second-leg"),
            ),
        ),
    ))

    def resolve(*_):
        return (first,)

    with pytest.raises(ValueError, match="consume a holding twice"):
        timeline.compile(candidate_resolver=resolve)


def test_resolver_cannot_turn_an_input_into_its_exact_output_holding():
    declared = HoldingKey("BAT-A", "BIN-SHARED", "each")
    transformed = HoldingKey("BAT-C", "BIN-SHARED", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-A-two", declared, 2, 1))
    timeline.record(ProcessEvent(
        "PROC-transform-one",
        "one-to-one transformation",
        moment(2),
        moment(2),
        inputs=(ProcessInput(
            "input",
            (declared,),
            ExactAmount(1),
            selector=selection(
                "SEL-input",
                "SKU-A",
                "BIN-SHARED",
                declared,
            ),
        ),),
        outputs=(ProcessOutput(
            "output",
            transformed,
            DISCRETE,
            OneToOneTransformedFromInput(
                "input",
                declared_one_to_one_transformation("SKU-A", "SKU-C"),
            ),
        ),),
    ))

    def resolve(*_):
        return (transformed,)

    with pytest.raises(ValueError, match="same-holding"):
        timeline.compile(candidate_resolver=resolve)


def test_ambiguous_input_needs_explicit_transformation_or_preserved_outputs():
    first = HoldingKey("BAT-A", "BIN-A", "each")
    second = HoldingKey("BAT-B", "BIN-A", "each")
    output = HoldingKey("BAT-A", "BIN-B", "each")
    with pytest.raises(ValueError, match="explicit one-to-one"):
        ProcessEvent(
            "PROC-ambiguous-move",
            "move",
            moment(1),
            moment(1),
            inputs=(ProcessInput(
                "moved",
                (first, second),
                ExactAmount(1),
                selector=selection(
                    "SEL-X",
                    "SKU-X",
                    "BIN-A",
                    first,
                    second,
                ),
            ),),
            outputs=(ProcessOutput(
                "destination",
                output,
                DISCRETE,
                FromInput("moved"),
            ),),
        )


def test_from_input_cannot_silently_change_batch_identity():
    source = HoldingKey("BAT-A", "BIN-A", "each")
    output = HoldingKey("BAT-B", "BIN-B", "each")

    with pytest.raises(ValueError, match="must preserve its input Batch"):
        ProcessEvent(
            "PROC-implicit-transformation",
            "implicit transformation",
            moment(1),
            moment(1),
            inputs=(ProcessInput("input", (source,), ExactAmount(1)),),
            outputs=(ProcessOutput(
                "output",
                output,
                DISCRETE,
                FromInput("input"),
            ),),
        )


def test_ambiguous_input_can_form_one_new_batch_with_correlated_provenance():
    timeline, first, second, transformed = ambiguous_transformation_timeline()

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(first), 5, 10)
    assert_bounds(compiled.current_bounds(second), 5, 10)
    assert_bounds(compiled.current_total_bounds((first, second)), 15, 15)
    assert_bounds(compiled.current_bounds(transformed), 5, 5)
    assert_bounds(compiled.output_source_allocation_bounds(
        "PROC-transform-five",
        "processed",
        first,
    ), 0, 5)
    assert_bounds(compiled.output_source_allocation_bounds(
        "PROC-transform-five",
        "processed",
        second,
    ), 0, 5)
    assert_bounds(compiled.output_source_allocation_total_bounds(
        "PROC-transform-five",
        "processed",
        (first, second),
    ), 5, 5)
    rendered = "\n".join(compiled.rendered_constraints())
    assert "PROC-transform-five:processed:one-to-one" in rendered
    assert "output-source-allocation[BAT-A @ BIN-SHARED" in rendered
    assert "output-source-allocation[BAT-B @ BIN-SHARED" in rendered


def test_later_audit_tightens_ambiguous_transformation_and_provenance():
    timeline, first, second, _ = ambiguous_transformation_timeline()
    timeline.record(exact_observation("OBS-A-seven-remain", first, 7, 3))

    historical = timeline.compile(known_at=moment(2, 13))
    assert_bounds(historical.output_source_allocation_bounds(
        "PROC-transform-five",
        "processed",
        first,
    ), 0, 5)

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(first), 7, 7)
    assert_bounds(compiled.current_bounds(second), 8, 8)
    assert_bounds(compiled.output_source_allocation_bounds(
        "PROC-transform-five",
        "processed",
        first,
    ), 3, 3)
    assert_bounds(compiled.output_source_allocation_bounds(
        "PROC-transform-five",
        "processed",
        second,
    ), 2, 2)


def test_one_to_one_transformation_respects_each_source_capacity():
    timeline, first, second, transformed = (
        ambiguous_transformation_timeline(2, 4)
    )

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(first), 0, 1)
    assert_bounds(compiled.current_bounds(second), 0, 1)
    assert_bounds(compiled.current_total_bounds((first, second)), 1, 1)
    assert_bounds(compiled.current_bounds(transformed), 5, 5)
    assert_bounds(compiled.output_source_allocation_bounds(
        "PROC-transform-five",
        "processed",
        first,
    ), 1, 2)
    assert_bounds(compiled.output_source_allocation_bounds(
        "PROC-transform-five",
        "processed",
        second,
    ), 3, 4)


def test_one_to_one_transformation_requires_a_fresh_output_batch():
    timeline, _, _, transformed = ambiguous_transformation_timeline()
    timeline.record(exact_observation(
        "OBS-output-already-exists",
        transformed,
        1,
        1,
    ))

    with pytest.raises(ValueError, match="output Batch already exists"):
        timeline.compile()


@pytest.mark.parametrize("process_id", ("AAA-transform", "ZZZ-transform"))
def test_same_time_observation_overlaps_fresh_transformed_batch_identity(
    process_id,
):
    timeline, _, _, transformed = ambiguous_transformation_timeline(
        process_id=process_id,
    )
    other_holding = HoldingKey(
        transformed.batch_id,
        "BIN-OTHER",
        transformed.unit,
    )
    timeline.record(exact_observation(
        "MMM-observation",
        other_holding,
        1,
        2,
    ))

    with pytest.raises(ValueError, match="effective_order"):
        timeline.compile()


def test_ambiguous_move_preserves_each_possible_batch_allocation():
    first_source = HoldingKey("BAT-A", "BIN-A", "each")
    second_source = HoldingKey("BAT-B", "BIN-A", "each")
    first_destination = HoldingKey("BAT-A", "BIN-B", "each")
    second_destination = HoldingKey("BAT-B", "BIN-B", "each")
    timeline = ProcessQuantityTimeline()
    timeline.record(exact_observation("OBS-A-ten", first_source, 10, 1))
    timeline.record(exact_observation("OBS-B-ten", second_source, 10, 1))
    timeline.record(ProcessEvent(
        "PROC-ambiguous-move",
        "move",
        moment(2),
        moment(2),
        inputs=(ProcessInput(
            "moved",
            (first_source, second_source),
            ExactAmount(5),
            selector=selection(
                "SEL-X",
                "SKU-X",
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

    compiled = timeline.compile()

    assert_bounds(compiled.current_bounds(first_source), 5, 10)
    assert_bounds(compiled.current_bounds(second_source), 5, 10)
    assert_bounds(compiled.current_total_bounds(
        (first_source, second_source),
    ), 15, 15)
    assert_bounds(compiled.current_bounds(first_destination), 0, 5)
    assert_bounds(compiled.current_bounds(second_destination), 0, 5)
    assert_bounds(compiled.current_total_bounds(
        (first_destination, second_destination),
    ), 5, 5)
