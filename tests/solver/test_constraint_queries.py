"""Mongo-free tests for the typed constraint-query boundary."""

from fractions import Fraction

import pytest

import inventorius.constraint_queries as constraint_queries
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
    QuantityConstraintSystem,
    QuantityDomain,
    QuantityQueryIndeterminate,
    QuantityVariable,
)


def variable(
    variable_id: str,
    *,
    unit: str = "each",
    domain: QuantityDomain = QuantityDomain.DISCRETE,
) -> QuantityVariable:
    return QuantityVariable(variable_id, unit, domain)


def fact(
    constraint_id: str,
    coefficients,
    relation: ConstraintRelation,
    bound,
) -> LinearConstraint:
    return LinearConstraint(
        constraint_id,
        tuple(sorted(
            (variable_id, Fraction(value))
            for variable_id, value in coefficients.items()
        )),
        relation,
        Fraction(bound),
    )


def bounded_snapshot(
    *,
    revision: int = 7,
    minimum=2,
    maximum=5,
) -> ConstraintGraphSnapshot:
    return ConstraintGraphSnapshot(
        revision,
        (variable("quantity"),),
        (
            fact(
                "quantity:lower",
                {"quantity": 1},
                ConstraintRelation.AT_LEAST,
                minimum,
            ),
            fact(
                "quantity:upper",
                {"quantity": 1},
                ConstraintRelation.AT_MOST,
                maximum,
            ),
        ),
    )


def test_capture_excludes_implicit_domain_facts_and_returns_typed_bounds():
    system = QuantityConstraintSystem()
    system.add_variable(variable("red"))
    system.add_constraint(
        "OBS-red:exact",
        {"red": 1},
        ConstraintRelation.EQUAL,
        25,
    )

    snapshot = ConstraintGraphSnapshot.capture(12, system)
    result = ConstraintQueryEvaluator().evaluate(
        snapshot,
        ExpressionBoundsQuery(ExactLinearExpression({"red": 1})),
    )

    assert tuple(item.constraint_id for item in snapshot.constraints) == (
        "OBS-red:exact",
    )
    assert result.graph_revision == 12
    assert result.status == QueryStatus.SOLVED
    assert result.unit == "each"
    assert result.domain == QuantityDomain.DISCRETE
    assert result.bounds is not None
    assert result.bounds.minimum == 25
    assert result.bounds.maximum == 25
    assert result.bounds.exact


def test_combined_expression_is_solved_directly_without_collapsing_ranges():
    snapshot = ConstraintGraphSnapshot(
        3,
        (variable("red-in-a"), variable("red-in-b")),
        (
            fact(
                "A:capacity",
                {"red-in-a": 1},
                ConstraintRelation.AT_MOST,
                24,
            ),
            fact(
                "B:capacity",
                {"red-in-b": 1},
                ConstraintRelation.AT_MOST,
                25,
            ),
            fact(
                "red:shared-total",
                {"red-in-a": 1, "red-in-b": 1},
                ConstraintRelation.EQUAL,
                25,
            ),
        ),
    )
    evaluator = ConstraintQueryEvaluator()

    in_a = evaluator.evaluate(
        snapshot,
        ExpressionBoundsQuery(ExactLinearExpression({"red-in-a": 1})),
    )
    in_b = evaluator.evaluate(
        snapshot,
        ExpressionBoundsQuery(ExactLinearExpression({"red-in-b": 1})),
    )
    combined = evaluator.evaluate(
        snapshot,
        ExpressionBoundsQuery(
            ExactLinearExpression({"red-in-a": 1, "red-in-b": 1})
        ),
    )

    assert (in_a.bounds.minimum, in_a.bounds.maximum) == (0, 24)
    assert (in_b.bounds.minimum, in_b.bounds.maximum) == (1, 25)
    assert (combined.bounds.minimum, combined.bounds.maximum) == (25, 25)


def test_overlay_narrows_a_query_and_is_discarded_after_each_evaluation():
    snapshot = bounded_snapshot(minimum=0, maximum=10)
    query = ExpressionBoundsQuery(ExactLinearExpression({"quantity": 1}))
    overlay = ConstraintOverlay(
        constraints=(
            fact(
                "OBS-hypothetical-count",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                4,
            ),
        )
    )
    evaluator = ConstraintQueryEvaluator()

    before = evaluator.evaluate(snapshot, query)
    hypothetical = evaluator.evaluate(snapshot, query, overlay=overlay)
    after = evaluator.evaluate(snapshot, query)

    assert (before.bounds.minimum, before.bounds.maximum) == (0, 10)
    assert (hypothetical.bounds.minimum, hypothetical.bounds.maximum) == (4, 4)
    assert after == before
    assert snapshot.revision == 7
    assert len(snapshot.constraints) == 2


def test_overlay_can_add_a_typed_variable_and_fact_referencing_the_base():
    snapshot = ConstraintGraphSnapshot(
        4,
        (variable("base"),),
        (
            fact(
                "base:exact",
                {"base": 1},
                ConstraintRelation.EQUAL,
                7,
            ),
        ),
    )
    overlay = ConstraintOverlay(
        variables=(variable("hypothetical-output"),),
        constraints=(
            fact(
                "hypothetical:conservation",
                {"base": 1, "hypothetical-output": -1},
                ConstraintRelation.EQUAL,
                0,
            ),
        ),
    )

    result = ConstraintQueryEvaluator().evaluate(
        snapshot,
        ExpressionBoundsQuery(
            ExactLinearExpression({"hypothetical-output": 1})
        ),
        overlay=overlay,
    )

    assert (result.bounds.minimum, result.bounds.maximum) == (7, 7)


@pytest.mark.parametrize(
    ("relation", "threshold", "possible", "guaranteed"),
    (
        (ConstraintRelation.AT_LEAST, 1, True, True),
        (ConstraintRelation.AT_LEAST, 4, True, False),
        (ConstraintRelation.AT_LEAST, 6, False, False),
        (ConstraintRelation.AT_MOST, 1, False, False),
        (ConstraintRelation.AT_MOST, 4, True, False),
        (ConstraintRelation.AT_MOST, 5, True, True),
    ),
)
def test_threshold_predicates_report_possible_and_guaranteed_separately(
    relation,
    threshold,
    possible,
    guaranteed,
):
    query = ThresholdPredicateQuery(
        ExactLinearExpression({"quantity": 1}),
        relation,
        threshold,
    )

    result = ConstraintQueryEvaluator().evaluate(bounded_snapshot(), query)

    assert result.status == QueryStatus.SOLVED
    assert result.threshold == threshold
    assert result.possible is possible
    assert result.guaranteed is guaranteed
    assert (result.bounds.minimum, result.bounds.maximum) == (2, 5)


@pytest.mark.parametrize("relation", (ConstraintRelation.EQUAL, "at-least"))
def test_threshold_predicate_rejects_untyped_or_unsupported_relations(relation):
    with pytest.raises(ValueError, match="AT_LEAST or AT_MOST"):
        ThresholdPredicateQuery(
            ExactLinearExpression({"quantity": 1}),
            relation,
            3,
        )


def test_fractional_coefficients_make_an_expression_continuous():
    result = ConstraintQueryEvaluator().evaluate(
        bounded_snapshot(minimum=2, maximum=4),
        ExpressionBoundsQuery(
            ExactLinearExpression({"quantity": Fraction(1, 2)})
        ),
    )

    assert result.domain == QuantityDomain.CONTINUOUS
    assert result.bounds.minimum == 1
    assert result.bounds.maximum == 2


def test_expression_query_returns_the_relevant_conflict_as_data():
    snapshot = ConstraintGraphSnapshot(
        8,
        (variable("quantity"),),
        (
            fact(
                "OBS-one",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                1,
            ),
            fact(
                "OBS-two",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                2,
            ),
        ),
    )

    result = ConstraintQueryEvaluator().evaluate(
        snapshot,
        ExpressionBoundsQuery(ExactLinearExpression({"quantity": 1})),
    )

    assert result.status == QueryStatus.CONFLICT
    assert result.bounds is None
    assert set(result.conflict_constraint_ids) == {"OBS-one", "OBS-two"}


def test_threshold_query_does_not_claim_truth_when_facts_conflict():
    snapshot = ConstraintGraphSnapshot(
        8,
        (variable("quantity"),),
        (
            fact(
                "OBS-one",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                1,
            ),
            fact(
                "OBS-two",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                2,
            ),
        ),
    )

    result = ConstraintQueryEvaluator().evaluate(
        snapshot,
        ThresholdPredicateQuery(
            ExactLinearExpression({"quantity": 1}),
            ConstraintRelation.AT_LEAST,
            1,
        ),
    )

    assert result.status == QueryStatus.CONFLICT
    assert result.possible is None
    assert result.guaranteed is None


def test_expression_query_returns_indeterminate_instead_of_guessing(monkeypatch):
    def indeterminate(*_args, **_kwargs):
        raise QuantityQueryIndeterminate("deterministic test result")

    monkeypatch.setattr(
        QuantityConstraintSystem,
        "expression_bounds",
        indeterminate,
    )

    result = ConstraintQueryEvaluator().evaluate(
        bounded_snapshot(),
        ExpressionBoundsQuery(ExactLinearExpression({"quantity": 1})),
    )

    assert result.status == QueryStatus.INDETERMINATE
    assert result.bounds is None


def test_each_expression_evaluation_rebuilds_a_fresh_system(monkeypatch):
    constructed = []
    original = constraint_queries.QuantityConstraintSystem

    class CountingSystem(original):
        def __init__(self, **kwargs):
            constructed.append(self)
            super().__init__(**kwargs)

    monkeypatch.setattr(
        constraint_queries,
        "QuantityConstraintSystem",
        CountingSystem,
    )
    evaluator = ConstraintQueryEvaluator()
    snapshot = bounded_snapshot()
    query = ExpressionBoundsQuery(ExactLinearExpression({"quantity": 1}))

    evaluator.evaluate(snapshot, query)
    evaluator.evaluate(snapshot, query)

    assert len(constructed) == 2
    assert constructed[0] is not constructed[1]


def test_consistent_counterfactual_is_distinct_from_guaranteed_safety():
    result = ConstraintQueryEvaluator().evaluate(
        bounded_snapshot(minimum=2, maximum=5),
        CounterfactualFeasibilityQuery(),
        overlay=ConstraintOverlay(
            constraints=(
                fact(
                    "MOVE-hypothesis",
                    {"quantity": 1},
                    ConstraintRelation.AT_LEAST,
                    4,
                ),
            )
        ),
    )

    assert result.classification == CounterfactualClassification.CONSISTENT
    assert not result.baseline_conflict_constraint_ids
    assert not result.augmented_conflict_constraint_ids


def test_counterfactual_reports_overlay_created_contradiction():
    result = ConstraintQueryEvaluator().evaluate(
        bounded_snapshot(minimum=2, maximum=5),
        CounterfactualFeasibilityQuery(),
        overlay=ConstraintOverlay(
            constraints=(
                fact(
                    "MOVE-six",
                    {"quantity": 1},
                    ConstraintRelation.AT_LEAST,
                    6,
                ),
            )
        ),
    )

    assert result.classification == CounterfactualClassification.CONTRADICTORY
    assert set(result.augmented_conflict_constraint_ids) == {
        "quantity:upper",
        "MOVE-six",
    }


def test_counterfactual_identifies_a_preexisting_baseline_conflict():
    snapshot = ConstraintGraphSnapshot(
        9,
        (variable("quantity"),),
        (
            fact(
                "OBS-one",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                1,
            ),
            fact(
                "OBS-two",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                2,
            ),
        ),
    )

    result = ConstraintQueryEvaluator().evaluate(
        snapshot,
        CounterfactualFeasibilityQuery(),
    )

    assert (
        result.classification
        == CounterfactualClassification.BASELINE_CONFLICTED
    )
    assert set(result.baseline_conflict_constraint_ids) == {
        "OBS-one",
        "OBS-two",
    }
    assert not result.augmented_conflict_constraint_ids


def test_malformed_overlay_fails_closed_even_when_baseline_is_conflicted():
    snapshot = ConstraintGraphSnapshot(
        9,
        (variable("quantity"),),
        (
            fact(
                "OBS-one",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                1,
            ),
            fact(
                "OBS-two",
                {"quantity": 1},
                ConstraintRelation.EQUAL,
                2,
            ),
        ),
    )
    malformed = ConstraintOverlay(
        constraints=(
            fact(
                "hypothesis:unknown",
                {"not-in-the-graph": 1},
                ConstraintRelation.EQUAL,
                1,
            ),
        )
    )

    with pytest.raises(ValueError, match="unknown quantity variable"):
        ConstraintQueryEvaluator().evaluate(
            snapshot,
            CounterfactualFeasibilityQuery(),
            overlay=malformed,
        )


def test_counterfactual_returns_indeterminate_for_bounded_policy_failure(
    monkeypatch,
):
    def indeterminate(*_args, **_kwargs):
        raise QuantityQueryIndeterminate("deterministic test result")

    monkeypatch.setattr(
        QuantityConstraintSystem,
        "is_feasible",
        indeterminate,
    )

    result = ConstraintQueryEvaluator().evaluate(
        bounded_snapshot(),
        CounterfactualFeasibilityQuery(),
    )

    assert result.classification == CounterfactualClassification.INDETERMINATE


@pytest.mark.parametrize(
    "revision",
    (-1, True, "revision-1"),
)
def test_snapshot_revision_is_narrow_nonnegative_integer_metadata(revision):
    with pytest.raises(ValueError, match="nonnegative integer"):
        ConstraintGraphSnapshot(revision)


def test_snapshot_and_overlay_reject_explicit_domain_constraints():
    implicit = fact(
        "domain:quantity:nonnegative",
        {"quantity": 1},
        ConstraintRelation.AT_LEAST,
        0,
    )

    with pytest.raises(ValueError, match="implicit"):
        ConstraintGraphSnapshot(1, (variable("quantity"),), (implicit,))
    with pytest.raises(ValueError, match="implicit"):
        ConstraintOverlay(constraints=(implicit,))


def test_overlay_rejects_duplicate_terms_before_mapping_can_hide_them():
    duplicate_terms = LinearConstraint(
        "hypothesis:duplicate",
        (("quantity", Fraction(1)), ("quantity", Fraction(-1))),
        ConstraintRelation.EQUAL,
        Fraction(0),
    )

    with pytest.raises(ValueError, match="duplicate terms"):
        ConstraintOverlay(constraints=(duplicate_terms,))


@pytest.mark.parametrize(
    ("overlay", "message"),
    (
        (
            ConstraintOverlay(variables=(variable("quantity"),)),
            "duplicate quantity variable",
        ),
        (
            ConstraintOverlay(
                constraints=(
                    fact(
                        "quantity:upper",
                        {"quantity": 1},
                        ConstraintRelation.AT_MOST,
                        3,
                    ),
                )
            ),
            "duplicate quantity constraint",
        ),
        (
            ConstraintOverlay(
                constraints=(
                    fact(
                        "hypothesis:unknown",
                        {"missing": 1},
                        ConstraintRelation.EQUAL,
                        1,
                    ),
                )
            ),
            "unknown quantity variable",
        ),
    ),
)
def test_overlay_collisions_and_unknown_references_fail_closed(overlay, message):
    with pytest.raises(ValueError, match=message):
        ConstraintQueryEvaluator().evaluate(
            bounded_snapshot(),
            CounterfactualFeasibilityQuery(),
            overlay=overlay,
        )


def test_overlay_rejects_constraints_that_mix_units():
    snapshot = ConstraintGraphSnapshot(
        1,
        (variable("items"), variable("liquid", unit="milliliter")),
    )
    overlay = ConstraintOverlay(
        constraints=(
            fact(
                "hypothesis:mixed-units",
                {"items": 1, "liquid": -1},
                ConstraintRelation.EQUAL,
                0,
            ),
        )
    )

    with pytest.raises(ValueError, match="cannot mix units"):
        ConstraintQueryEvaluator().evaluate(
            snapshot,
            CounterfactualFeasibilityQuery(),
            overlay=overlay,
        )


def test_snapshot_and_overlay_copy_mutable_constraint_terms():
    snapshot_terms = [["quantity", Fraction(1)]]
    snapshot = ConstraintGraphSnapshot(
        5,
        (variable("quantity"),),
        (
            LinearConstraint(
                "snapshot:exact",
                snapshot_terms,
                ConstraintRelation.EQUAL,
                Fraction(2),
            ),
        ),
    )
    overlay_terms = [["quantity", Fraction(1)]]
    overlay = ConstraintOverlay(
        constraints=(
            LinearConstraint(
                "overlay:exact",
                overlay_terms,
                ConstraintRelation.EQUAL,
                Fraction(3),
            ),
        ),
    )

    snapshot_terms[0][1] = Fraction(2)
    overlay_terms[0][1] = Fraction(3)
    evaluator = ConstraintQueryEvaluator()
    query = ExpressionBoundsQuery(ExactLinearExpression({"quantity": 1}))
    snapshot_result = evaluator.evaluate(snapshot, query)
    overlay_result = evaluator.evaluate(
        ConstraintGraphSnapshot(6, (variable("quantity"),)),
        query,
        overlay=overlay,
    )

    assert snapshot.constraints[0].coefficients == (
        ("quantity", Fraction(1)),
    )
    assert overlay.constraints[0].coefficients == (
        ("quantity", Fraction(1)),
    )
    assert snapshot_result.bounds.exact
    assert snapshot_result.bounds.minimum == 2
    assert overlay_result.bounds.exact
    assert overlay_result.bounds.minimum == 3


def test_query_rejects_unknown_variables_and_mixed_units():
    snapshot = ConstraintGraphSnapshot(
        1,
        (variable("items"), variable("liquid", unit="milliliter")),
    )
    evaluator = ConstraintQueryEvaluator()

    with pytest.raises(ValueError, match="unknown quantity variable"):
        evaluator.evaluate(
            snapshot,
            ExpressionBoundsQuery(ExactLinearExpression({"unknown": 1})),
        )
    with pytest.raises(ValueError, match="cannot mix units"):
        evaluator.evaluate(
            snapshot,
            ExpressionBoundsQuery(
                ExactLinearExpression({"items": 1, "liquid": 1})
            ),
        )


@pytest.mark.parametrize("invalid", (True, 1.5, "not-a-number"))
def test_exact_expression_rejects_non_exact_numbers(invalid):
    with pytest.raises(ValueError, match="exact number|int, decimal string"):
        ExactLinearExpression({"quantity": invalid})
