"""Executable physical scenarios for constraint-native quantities."""

from fractions import Fraction

import pytest

import inventorius.quantity_constraints as quantity_constraints
from inventorius.quantity_constraints import (
    InfeasibleQuantityFacts,
    ObservationBasis,
    QuantityDomain,
    QuantityHistory,
    QuantityObservation,
    QuantityQueryIndeterminate,
)
from inventorius.ledger import HoldingKey


FASTENERS = HoldingKey(
    "BAT-FASTENERS",
    "BIN-FASTENERS",
    "each",
)


def assert_bounds(actual, minimum, maximum):
    assert actual.minimum == (
        None if minimum is None else Fraction(str(minimum))
    )
    assert actual.maximum == (
        None if maximum is None else Fraction(str(maximum))
    )


def estimated_fasteners():
    return QuantityObservation(
        "OBS-opening-estimate",
        lower=40,
        preferred=50,
        upper=60,
        basis=ObservationBasis.ESTIMATED,
    )


def test_known_withdrawal_and_recount_refine_the_original_estimate():
    history = QuantityHistory()
    opening = history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        estimated_fasteners(),
    )

    remaining = history.record_exact_withdrawal("OP-use-forty", FASTENERS, 40)
    assert_bounds(history.bounds(remaining), 0, 20)

    history.observe_current(
        FASTENERS,
        QuantityObservation.exact(
            "OBS-count-twenty",
            20,
            basis=ObservationBasis.COUNTED,
        ),
    )

    assert_bounds(history.current_physical_bounds(FASTENERS), 20, 20)
    assert_bounds(history.bounds(opening), 60, 60)
    assert history.is_feasible()


def test_preferred_estimate_is_retained_but_does_not_constrain_truth():
    history = QuantityHistory()
    opening = history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        estimated_fasteners(),
    )

    assert history.observations[0][1].preferred == 50
    history.observe_current(
        FASTENERS,
        QuantityObservation.exact(
            "OBS-count-sixty",
            60,
            basis=ObservationBasis.COUNTED,
        ),
    )

    assert_bounds(history.bounds(opening), 60, 60)


def test_conflicting_recount_names_the_incompatible_physical_facts():
    history = QuantityHistory()
    history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        estimated_fasteners(),
    )
    history.record_exact_withdrawal("OP-use-forty", FASTENERS, 40)
    history.observe_current(
        FASTENERS,
        QuantityObservation.exact(
            "OBS-count-twenty-five",
            25,
            basis=ObservationBasis.COUNTED,
        ),
    )

    assert not history.is_feasible()
    assert set(history.conflict()) == {
        "OBS-opening-estimate:upper",
        "OP-use-forty:balance",
        "OBS-count-twenty-five:exact",
    }
    with pytest.raises(InfeasibleQuantityFacts) as failure:
        history.current_physical_bounds(FASTENERS)
    assert set(failure.value.fact_ids) == set(history.conflict())


def test_one_conflicted_holding_does_not_block_an_unrelated_quantity_query():
    unrelated = HoldingKey(
        "BAT-LIQUID",
        "BIN-LIQUID",
        "liter",
    )
    history = QuantityHistory()
    history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        estimated_fasteners(),
    )
    history.record_exact_withdrawal("OP-use-forty", FASTENERS, 40)
    history.observe_current(
        FASTENERS,
        QuantityObservation.exact(
            "OBS-impossible-recount",
            25,
            basis=ObservationBasis.COUNTED,
        ),
    )
    history.open_holding(
        unrelated,
        QuantityDomain.CONTINUOUS,
        QuantityObservation.exact(
            "OBS-liquid-one-liter",
            1,
            basis=ObservationBasis.MEASURED,
        ),
    )

    assert not history.is_feasible()
    assert_bounds(history.current_physical_bounds(unrelated), 1, 1)


def test_unknown_two_bin_allocation_preserves_the_shared_total():
    first = HoldingKey(
        "BAT-FASTENERS",
        "BIN-A",
        "each",
    )
    second = HoldingKey(
        "BAT-FASTENERS",
        "BIN-B",
        "each",
    )
    history = QuantityHistory()
    history.open_holding(
        first,
        QuantityDomain.DISCRETE,
        QuantityObservation.exact(
            "OBS-A-fifty",
            50,
            basis=ObservationBasis.COUNTED,
        ),
    )
    history.open_holding(
        second,
        QuantityDomain.DISCRETE,
        QuantityObservation.exact(
            "OBS-B-thirty",
            30,
            basis=ObservationBasis.COUNTED,
        ),
    )

    first_after, second_after = history.record_withdrawal_from_sources(
        "OP-use-forty-from-two-bins",
        (first, second),
        40,
    )

    assert_bounds(history.bounds(first_after), 10, 40)
    assert_bounds(history.bounds(second_after), 0, 30)
    assert_bounds(history.current_total_bounds((first, second)), 40, 40)
    assert_bounds(
        history.withdrawal_bounds("OP-use-forty-from-two-bins", first),
        10,
        40,
    )
    assert_bounds(
        history.withdrawal_bounds("OP-use-forty-from-two-bins", second),
        0,
        30,
    )
    allocation_explanation = history.explain_withdrawal(
        "OP-use-forty-from-two-bins",
        first,
    )
    assert_bounds(allocation_explanation.bounds, 10, 40)
    assert "OP-use-forty-from-two-bins:total" in (
        allocation_explanation.minimum_fact_ids
    )

    history.observe_current(
        first,
        QuantityObservation.exact(
            "OBS-A-recount-thirty-five",
            35,
            basis=ObservationBasis.COUNTED,
        ),
    )
    assert_bounds(history.current_physical_bounds(second), 5, 5)
    assert_bounds(
        history.withdrawal_bounds("OP-use-forty-from-two-bins", first),
        15,
        15,
    )


def test_two_source_integer_bounds_match_all_small_feasible_allocations():
    for first_amount in range(1, 6):
        for second_amount in range(1, 6):
            for total in range(1, first_amount + second_amount + 1):
                first = HoldingKey(
                    "BAT-SHARED",
                    "BIN-A",
                    "each",
                )
                second = HoldingKey(
                    "BAT-SHARED",
                    "BIN-B",
                    "each",
                )
                history = QuantityHistory()
                history.open_holding(
                    first,
                    QuantityDomain.DISCRETE,
                    QuantityObservation.exact(
                        "OBS-A",
                        first_amount,
                        basis=ObservationBasis.COUNTED,
                    ),
                )
                history.open_holding(
                    second,
                    QuantityDomain.DISCRETE,
                    QuantityObservation.exact(
                        "OBS-B",
                        second_amount,
                        basis=ObservationBasis.COUNTED,
                    ),
                )
                history.record_withdrawal_from_sources(
                    "OP-shared-use",
                    (first, second),
                    total,
                )

                expected_minimum = max(0, total - second_amount)
                expected_maximum = min(first_amount, total)
                assert_bounds(
                    history.withdrawal_bounds("OP-shared-use", first),
                    expected_minimum,
                    expected_maximum,
                )


def test_continuous_spool_measurement_keeps_exact_decimal_fractions():
    spool = HoldingKey(
        "BAT-WIRE",
        "BIN-WIRE",
        "meter",
    )
    history = QuantityHistory()
    history.open_holding(
        spool,
        QuantityDomain.CONTINUOUS,
        QuantityObservation(
            "OBS-spool-estimate",
            lower="125.5",
            preferred="128.0",
            upper="130.25",
            basis=ObservationBasis.MEASURED,
        ),
    )

    remaining = history.record_exact_withdrawal("OP-cut-wire", spool, "2.75")

    assert_bounds(history.bounds(remaining), "122.75", "127.5")


def test_bounds_explanation_omits_irrelevant_facts():
    unrelated = HoldingKey(
        "BAT-UNRELATED",
        "BIN-OTHER",
        "each",
    )
    history = QuantityHistory()
    history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        estimated_fasteners(),
    )
    history.open_holding(
        unrelated,
        QuantityDomain.DISCRETE,
        QuantityObservation.exact(
            "OBS-unrelated",
            100,
            basis=ObservationBasis.COUNTED,
        ),
    )
    remaining = history.record_exact_withdrawal("OP-use-forty", FASTENERS, 40)

    explanation = history.explain(remaining)

    assert_bounds(explanation.bounds, 0, 20)
    assert "OBS-unrelated:exact" not in explanation.minimum_fact_ids
    assert "OBS-unrelated:exact" not in explanation.maximum_fact_ids
    assert "OBS-opening-estimate:lower" not in explanation.maximum_fact_ids
    assert "OBS-opening-estimate:upper" in explanation.maximum_fact_ids
    assert "OP-use-forty:balance" in explanation.maximum_fact_ids


def test_discrete_and_unit_boundaries_fail_closed_before_partial_changes():
    history = QuantityHistory()
    with pytest.raises(ValueError, match="whole amounts"):
        history.open_holding(
            FASTENERS,
            QuantityDomain.DISCRETE,
            QuantityObservation(
                "OBS-half-fastener",
                lower="0.5",
                upper=1,
                basis=ObservationBasis.ESTIMATED,
            ),
        )
    assert history.constraints == ()

    history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        estimated_fasteners(),
    )
    liquid = HoldingKey(
        "BAT-LIQUID",
        "BIN-LIQUID",
        "liter",
    )
    history.open_holding(
        liquid,
        QuantityDomain.CONTINUOUS,
        QuantityObservation.exact(
            "OBS-liquid",
            1,
            basis=ObservationBasis.MEASURED,
        ),
    )
    before = history.constraints

    with pytest.raises(ValueError, match="one compatible batch, unit"):
        history.record_withdrawal_from_sources(
            "OP-mixed-dimensions",
            (FASTENERS, liquid),
            1,
        )
    assert history.constraints == before


def test_preferred_only_observation_does_not_become_a_false_bound():
    history = QuantityHistory()
    history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        QuantityObservation(
            "OBS-about-fifty",
            preferred=50,
            basis=ObservationBasis.ESTIMATED,
        ),
    )

    assert_bounds(history.current_physical_bounds(FASTENERS), 0, None)


def test_quantity_history_reuses_package_aware_canonical_holding_identity():
    loose = HoldingKey("BAT-PART", "BIN-A", "each")
    boxed = HoldingKey("BAT-PART", "BIN-A", "each", "PKG-BOX")
    history = QuantityHistory()
    history.open_holding(
        loose,
        QuantityDomain.DISCRETE,
        QuantityObservation.exact(
            "OBS-loose-ten",
            10,
            basis=ObservationBasis.COUNTED,
        ),
    )
    history.open_holding(
        boxed,
        QuantityDomain.DISCRETE,
        QuantityObservation.exact(
            "OBS-boxed-two",
            2,
            basis=ObservationBasis.COUNTED,
        ),
    )

    assert_bounds(history.current_physical_bounds(loose), 10, 10)
    assert_bounds(history.current_physical_bounds(boxed), 2, 2)
    with pytest.raises(ValueError, match="package configuration"):
        history.current_total_bounds((loose, boxed))
    with pytest.raises(ValueError, match="package configuration"):
        history.record_withdrawal_from_sources(
            "OP-mixed-package-shapes",
            (loose, boxed),
            1,
        )

    with pytest.raises(ValueError, match="already has an opening state"):
        history.open_holding(
            loose,
            QuantityDomain.CONTINUOUS,
            QuantityObservation.exact(
                "OBS-competing-domain",
                10,
                basis=ObservationBasis.MEASURED,
            ),
        )


def test_current_total_rejects_duplicate_holdings_and_explains_correlation():
    first = HoldingKey("BAT-SHARED", "BIN-A", "each")
    second = HoldingKey("BAT-SHARED", "BIN-B", "each")
    history = QuantityHistory()
    for holding, observation_id, amount in (
        (first, "OBS-first", 50),
        (second, "OBS-second", 30),
    ):
        history.open_holding(
            holding,
            QuantityDomain.DISCRETE,
            QuantityObservation.exact(
                observation_id,
                amount,
                basis=ObservationBasis.COUNTED,
            ),
        )
    history.record_withdrawal_from_sources(
        "OP-shared",
        (first, second),
        40,
    )

    with pytest.raises(ValueError, match="distinct holdings"):
        history.current_total_bounds((first, first))

    explanation = history.explain_current_total((first, second))
    assert_bounds(explanation.bounds, 40, 40)
    assert "OP-shared:total" in explanation.minimum_fact_ids
    assert "OP-shared:total" in explanation.maximum_fact_ids


def test_recorded_overdraw_is_preserved_as_conflicting_physical_evidence():
    history = QuantityHistory()
    history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        QuantityObservation.exact(
            "OBS-five",
            5,
            basis=ObservationBasis.COUNTED,
        ),
    )

    history.record_exact_withdrawal("OP-record-seven-used", FASTENERS, 7)

    assert not history.is_feasible()
    with pytest.raises(InfeasibleQuantityFacts):
        history.current_physical_bounds(FASTENERS)


def test_rejected_event_does_not_advance_the_evidence_history():
    unknown = HoldingKey("BAT-UNKNOWN", "BIN-UNKNOWN", "each")
    history = QuantityHistory()
    history.open_holding(
        FASTENERS,
        QuantityDomain.DISCRETE,
        estimated_fasteners(),
    )
    before = history.constraints

    with pytest.raises(ValueError, match="no quantity state"):
        history.record_exact_withdrawal("OP-unknown", unknown, 1)
    assert history.constraints == before

    next_state = history.record_exact_withdrawal("OP-valid", FASTENERS, 1)
    assert next_state.variable_id == "quantity_1"

    after = history.constraints
    with pytest.raises(ValueError, match="duplicate quantity event"):
        history.record_exact_withdrawal("OP-valid", FASTENERS, 1)
    assert history.constraints == after


def test_sequential_three_source_withdrawals_retain_joint_conservation():
    holdings = tuple(
        HoldingKey("BAT-SHARED", f"BIN-{suffix}", "each")
        for suffix in ("A", "B", "C")
    )
    history = QuantityHistory()
    for index, holding in enumerate(holdings):
        history.open_holding(
            holding,
            QuantityDomain.DISCRETE,
            QuantityObservation.exact(
                f"OBS-opening-{index}",
                10,
                basis=ObservationBasis.COUNTED,
            ),
        )

    history.record_withdrawal_from_sources("OP-first", holdings, 12)
    history.record_withdrawal_from_sources("OP-second", holdings[1:], 5)

    assert_bounds(history.current_total_bounds(holdings), 13, 13)


def test_indeterminate_solver_result_is_not_reported_as_infeasible(monkeypatch):
    class IndeterminateSolver:
        @staticmethod
        def set(**_kwargs):
            return None

        @staticmethod
        def add(*_constraints):
            return None

        @staticmethod
        def check():
            return quantity_constraints.z3.unknown

        @staticmethod
        def reason_unknown():
            return "deterministic test result"

    monkeypatch.setattr(
        quantity_constraints.z3,
        "Solver",
        IndeterminateSolver,
    )
    system = quantity_constraints.QuantityConstraintSystem()

    with pytest.raises(QuantityQueryIndeterminate, match="indeterminate"):
        system.is_feasible()


def test_end_to_end_query_budget_applies_across_solver_calls(monkeypatch):
    moments = iter((0.0, 1.0))
    monkeypatch.setattr(
        quantity_constraints,
        "monotonic",
        lambda: next(moments),
    )
    system = quantity_constraints.QuantityConstraintSystem(timeout_ms=1)

    with pytest.raises(QuantityQueryIndeterminate, match="end-to-end"):
        system.is_feasible()
