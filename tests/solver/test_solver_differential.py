"""Differential physical scenarios for the typed query-time solver seam.

The production side expresses physical conservation as named linear facts and
asks typed queries through ``ConstraintQueryEvaluator``.  Expected answers come
from ``reference_oracle``, which uses only bounded Python enumeration.
"""

from fractions import Fraction

import pytest

from inventorius.constraint_queries import (
    ConstraintGraphSnapshot,
    ConstraintOverlay,
    ConstraintQueryEvaluator,
    CounterfactualClassification,
    CounterfactualFeasibilityQuery,
    ExactLinearExpression,
    ExpressionBoundsQuery,
    QueryStatus,
    ThresholdPredicateQuery,
)
from inventorius.quantity_constraints import (
    ConstraintRelation,
    LinearConstraint,
    QuantityDomain,
    QuantityVariable,
)
from tests.solver.reference_oracle import (
    EventGroup,
    FiniteHistoryOracle,
    LEDAllocationScenario,
)


DISCRETE = QuantityDomain.DISCRETE


def _variable(variable_id: str) -> QuantityVariable:
    return QuantityVariable(variable_id, "each", DISCRETE)


def _fact(
    constraint_id: str,
    coefficients: dict[str, int],
    relation: ConstraintRelation,
    bound: int,
) -> LinearConstraint:
    return LinearConstraint(
        constraint_id,
        tuple(sorted(
            (variable_id, Fraction(coefficient))
            for variable_id, coefficient in coefficients.items()
        )),
        relation,
        Fraction(bound),
    )


def _led_snapshot(
    scenario: LEDAllocationScenario,
    *,
    revision: int = 1,
) -> ConstraintGraphSnapshot:
    """Compile the LED story independently from the finite-world oracle."""

    variable_ids = (
        "red-in-a",
        "blue-in-a",
        "red-in-b",
        "blue-in-b",
        "red-remaining",
        "blue-remaining",
        "red-in-final",
        "blue-in-final",
    )
    return ConstraintGraphSnapshot(
        revision,
        tuple(_variable(variable_id) for variable_id in variable_ids),
        (
            _fact(
                "opening:red-conservation",
                {"red-in-a": 1, "red-in-b": 1, "red-remaining": 1},
                ConstraintRelation.EQUAL,
                scenario.opening_red,
            ),
            _fact(
                "opening:blue-conservation",
                {"blue-in-a": 1, "blue-in-b": 1, "blue-remaining": 1},
                ConstraintRelation.EQUAL,
                scenario.opening_blue,
            ),
            _fact(
                "process-a:total-leds",
                {"red-in-a": 1, "blue-in-a": 1},
                ConstraintRelation.EQUAL,
                scenario.part_a_size,
            ),
            _fact(
                "process-b:total-leds",
                {"red-in-b": 1, "blue-in-b": 1},
                ConstraintRelation.EQUAL,
                scenario.part_b_size,
            ),
            _fact(
                "final:red-provenance",
                {"red-in-final": 1, "red-in-a": -1, "red-in-b": -1},
                ConstraintRelation.EQUAL,
                0,
            ),
            _fact(
                "final:blue-provenance",
                {
                    "blue-in-final": 1,
                    "blue-in-a": -1,
                    "blue-in-b": -1,
                },
                ConstraintRelation.EQUAL,
                0,
            ),
        ),
    )


def _bounds(
    snapshot: ConstraintGraphSnapshot,
    coefficients: dict[str, int],
    *,
    overlay: ConstraintOverlay | None = None,
) -> tuple[Fraction | None, Fraction | None]:
    result = ConstraintQueryEvaluator().evaluate(
        snapshot,
        ExpressionBoundsQuery(ExactLinearExpression(coefficients)),
        overlay=overlay,
    )
    assert result.status == QueryStatus.SOLVED
    assert result.bounds is not None
    return result.bounds.minimum, result.bounds.maximum


def test_corrected_led_story_is_query_specific_and_matches_the_oracle():
    scenario = LEDAllocationScenario(25, 25, 24, 25)
    oracle = scenario.oracle()
    snapshot = _led_snapshot(scenario, revision=41)

    production_answers = {
        "part-a": _bounds(snapshot, {"red-in-a": 1}),
        "part-b": _bounds(snapshot, {"red-in-b": 1}),
        "both-parts": _bounds(
            snapshot,
            {"red-in-a": 1, "red-in-b": 1},
        ),
        "final": _bounds(snapshot, {"red-in-final": 1}),
        "blue-final": _bounds(snapshot, {"blue-in-final": 1}),
        "final-total": _bounds(
            snapshot,
            {"red-in-final": 1, "blue-in-final": 1},
        ),
    }
    oracle_answers = {
        "part-a": oracle.expression_bounds(
            lambda world: world["red_in_a"]
        ),
        "part-b": oracle.expression_bounds(
            lambda world: world["red_in_b"]
        ),
        "both-parts": oracle.expression_bounds(scenario.red_used),
        "final": oracle.expression_bounds(scenario.red_used),
        "blue-final": oracle.expression_bounds(scenario.blue_used),
        "final-total": oracle.expression_bounds(
            lambda world: scenario.red_used(world) + scenario.blue_used(world)
        ),
    }

    assert production_answers == {
        name: (Fraction(answer.minimum), Fraction(answer.maximum))
        for name, answer in oracle_answers.items()
    }
    assert production_answers == {
        "part-a": (Fraction(0), Fraction(24)),
        "part-b": (Fraction(0), Fraction(25)),
        "both-parts": (Fraction(24), Fraction(25)),
        "final": (Fraction(24), Fraction(25)),
        "blue-final": (Fraction(24), Fraction(25)),
        "final-total": (Fraction(49), Fraction(49)),
    }


def test_later_blue_observation_tightens_only_the_new_graph_revision():
    scenario = LEDAllocationScenario(25, 25, 24, 25)
    snapshot = _led_snapshot(scenario, revision=41)
    observed_snapshot = ConstraintGraphSnapshot(
        42,
        snapshot.variables,
        (
            *snapshot.constraints,
            _fact(
                "observation:one-blue-remains",
                {"blue-remaining": 1},
                ConstraintRelation.EQUAL,
                1,
            ),
        ),
    )

    before = _bounds(snapshot, {"red-in-final": 1})
    observed = _bounds(observed_snapshot, {"red-in-final": 1})
    observed_blue = _bounds(observed_snapshot, {"blue-in-final": 1})
    observed_total = _bounds(
        observed_snapshot,
        {"red-in-final": 1, "blue-in-final": 1},
    )
    after = _bounds(snapshot, {"red-in-final": 1})
    oracle_answer = scenario.oracle(
        observed_remaining_blue=1
    ).expression_bounds(scenario.red_used)

    assert before == (Fraction(24), Fraction(25))
    assert observed == (
        Fraction(oracle_answer.minimum),
        Fraction(oracle_answer.maximum),
    ) == (Fraction(25), Fraction(25))
    assert observed_blue == (Fraction(24), Fraction(24))
    assert observed_total == (Fraction(49), Fraction(49))
    assert after == before
    assert snapshot.revision == 41
    assert observed_snapshot.revision == 42


def test_generated_small_led_histories_match_independent_enumeration():
    checked = 0
    for opening_red in range(5):
        for opening_blue in range(5):
            available = opening_red + opening_blue
            for part_a_size in range(available + 1):
                for part_b_size in range(available - part_a_size + 1):
                    scenario = LEDAllocationScenario(
                        opening_red,
                        opening_blue,
                        part_a_size,
                        part_b_size,
                    )
                    expected = scenario.oracle().expression_bounds(
                        scenario.red_used
                    )
                    actual = _bounds(
                        _led_snapshot(scenario),
                        {"red-in-final": 1},
                    )

                    assert actual == (
                        Fraction(expected.minimum),
                        Fraction(expected.maximum),
                    )
                    checked += 1

    assert checked == 425


@pytest.mark.parametrize(
    (
        "minimum",
        "maximum",
        "expected_possible",
        "expected_guaranteed",
        "expected_counterfactual",
    ),
    (
        (20, 30, True, True, CounterfactualClassification.CONSISTENT),
        (10, 30, True, False, CounterfactualClassification.CONSISTENT),
        (0, 19, False, False, CounterfactualClassification.CONTRADICTORY),
    ),
)
def test_move_of_twenty_distinguishes_possible_guaranteed_and_conflicting(
    minimum,
    maximum,
    expected_possible,
    expected_guaranteed,
    expected_counterfactual,
):
    snapshot = ConstraintGraphSnapshot(
        9,
        (_variable("source-quantity"),),
        (
            _fact(
                "source:lower",
                {"source-quantity": 1},
                ConstraintRelation.AT_LEAST,
                minimum,
            ),
            _fact(
                "source:upper",
                {"source-quantity": 1},
                ConstraintRelation.AT_MOST,
                maximum,
            ),
        ),
    )
    proposed_move = ConstraintOverlay(
        constraints=(
            _fact(
                "proposed-move:needs-twenty",
                {"source-quantity": 1},
                ConstraintRelation.AT_LEAST,
                20,
            ),
        ),
    )
    evaluator = ConstraintQueryEvaluator()

    availability = evaluator.evaluate(
        snapshot,
        ThresholdPredicateQuery(
            ExactLinearExpression({"source-quantity": 1}),
            ConstraintRelation.AT_LEAST,
            20,
        ),
    )
    counterfactual = evaluator.evaluate(
        snapshot,
        CounterfactualFeasibilityQuery(),
        overlay=proposed_move,
    )

    assert availability.possible is expected_possible
    assert availability.guaranteed is expected_guaranteed
    assert counterfactual.classification == expected_counterfactual


def test_counterfactual_names_the_same_minimal_conflict_as_enumeration():
    snapshot = ConstraintGraphSnapshot(
        17,
        (_variable("quantity"),),
        (
            _fact(
                "base-opening",
                {"quantity": 1},
                ConstraintRelation.AT_MOST,
                5,
            ),
        ),
    )
    candidate_facts = {
        "process-x": _fact(
            "process-x",
            {"quantity": 1},
            ConstraintRelation.AT_LEAST,
            2,
        ),
        "process-y": _fact(
            "process-y",
            {"quantity": 1},
            ConstraintRelation.AT_MOST,
            3,
        ),
        "process-z": _fact(
            "process-z",
            {"quantity": 1},
            ConstraintRelation.AT_MOST,
            5,
        ),
        "observation-a": _fact(
            "observation-a",
            {"quantity": 1},
            ConstraintRelation.EQUAL,
            4,
        ),
    }
    evaluator = ConstraintQueryEvaluator()
    complete_overlay = ConstraintOverlay(
        constraints=tuple(candidate_facts.values())
    )
    production = evaluator.evaluate(
        snapshot,
        CounterfactualFeasibilityQuery(),
        overlay=complete_overlay,
    )
    oracle = FiniteHistoryOracle(
        {"quantity": range(6)},
        (
            EventGroup.one("base-opening", lambda world: world["quantity"] <= 5),
            EventGroup.one("process-x", lambda world: world["quantity"] >= 2),
            EventGroup.one("process-y", lambda world: world["quantity"] <= 3),
            EventGroup.one("process-z", lambda world: world["quantity"] <= 5),
            EventGroup.one(
                "observation-a",
                lambda world: world["quantity"] == 4,
            ),
        ),
    )
    oracle_conflicts = oracle.deletion_minimal_conflicts(
        tuple(candidate_facts),
        fixed_group_ids=("base-opening",),
    )

    assert production.classification == CounterfactualClassification.CONTRADICTORY
    assert oracle_conflicts == (("process-y", "observation-a"),)
    assert set(production.augmented_conflict_constraint_ids) == set(
        oracle_conflicts[0]
    )

    without_y = evaluator.evaluate(
        snapshot,
        CounterfactualFeasibilityQuery(),
        overlay=ConstraintOverlay(constraints=tuple(
            fact
            for event_id, fact in candidate_facts.items()
            if event_id != "process-y"
        )),
    )
    without_x = evaluator.evaluate(
        snapshot,
        CounterfactualFeasibilityQuery(),
        overlay=ConstraintOverlay(constraints=tuple(
            fact
            for event_id, fact in candidate_facts.items()
            if event_id != "process-x"
        )),
    )

    assert without_y.classification == CounterfactualClassification.CONSISTENT
    assert without_x.classification == CounterfactualClassification.CONTRADICTORY
