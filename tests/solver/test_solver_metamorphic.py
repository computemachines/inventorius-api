"""Metamorphic checks for the persistence-free quantity solver seam."""

from datetime import datetime, timezone
from fractions import Fraction

from inventorius.constraint_queries import (
    ConstraintGraphSnapshot,
    ConstraintOverlay,
    ConstraintQueryEvaluator,
    ExactLinearExpression,
    ExpressionBoundsQuery,
)
from inventorius.ledger import HoldingKey
from inventorius.process_quantities import (
    ObservationEvent,
    ProcessQuantityTimeline,
)
from inventorius.quantity_constraints import (
    ConstraintRelation,
    LinearConstraint,
    ObservationBasis,
    QuantityConstraintSystem,
    QuantityDomain,
    QuantityObservation,
    QuantityVariable,
)


DISCRETE = QuantityDomain.DISCRETE


def _bounds_pair(bounds):
    return bounds.minimum, bounds.maximum


def _bounded_variable_system(prefix: str = ""):
    """Build one tiny model whose identifiers may be consistently renamed."""

    system = QuantityConstraintSystem()
    primary = f"{prefix}primary"
    companion = f"{prefix}companion"
    system.add_variable(QuantityVariable(primary, "each", DISCRETE))
    system.add_variable(QuantityVariable(companion, "each", DISCRETE))
    system.add_constraint(
        f"{prefix}combined-total",
        {primary: 1, companion: 1},
        ConstraintRelation.EQUAL,
        12,
    )
    system.add_constraint(
        f"{prefix}companion-capacity",
        {companion: 1},
        ConstraintRelation.AT_MOST,
        5,
    )
    system.add_constraint(
        f"{prefix}primary-capacity",
        {primary: 1},
        ConstraintRelation.AT_MOST,
        10,
    )
    return system, primary


def test_adding_consistent_evidence_can_only_narrow_an_answer():
    system = QuantityConstraintSystem()
    system.add_variable(QuantityVariable("quantity", "each", DISCRETE))
    system.add_constraint(
        "opening-upper",
        {"quantity": 1},
        ConstraintRelation.AT_MOST,
        10,
    )

    before = system.bounds("quantity")
    system.add_constraint(
        "later-lower",
        {"quantity": 1},
        ConstraintRelation.AT_LEAST,
        4,
    )
    after = system.bounds("quantity")

    assert _bounds_pair(before) == (Fraction(0), Fraction(10))
    assert _bounds_pair(after) == (Fraction(4), Fraction(10))
    assert after.minimum >= before.minimum
    assert after.maximum <= before.maximum


def test_adding_incompatible_evidence_reports_a_conflict():
    system = QuantityConstraintSystem()
    system.add_variable(QuantityVariable("quantity", "each", DISCRETE))
    system.add_constraint(
        "known-lower",
        {"quantity": 1},
        ConstraintRelation.AT_LEAST,
        4,
    )
    assert system.is_feasible()

    system.add_constraint(
        "contradictory-upper",
        {"quantity": 1},
        ConstraintRelation.AT_MOST,
        3,
    )

    assert not system.is_feasible()
    assert set(system.conflict()) == {
        "known-lower",
        "contradictory-upper",
    }


def test_disconnected_facts_do_not_change_a_connected_expression():
    system, primary = _bounded_variable_system()
    before = system.bounds(primary)

    system.add_variable(QuantityVariable("unrelated", "each", DISCRETE))
    system.add_constraint(
        "unrelated-exact",
        {"unrelated": 1},
        ConstraintRelation.EQUAL,
        99,
    )

    assert _bounds_pair(before) == (Fraction(7), Fraction(10))
    assert system.bounds(primary) == before


def test_consistent_identifier_renaming_preserves_solver_answers():
    original, original_primary = _bounded_variable_system()
    renamed, renamed_primary = _bounded_variable_system("renamed-")

    assert original.bounds(original_primary) == renamed.bounds(renamed_primary)
    assert original.is_feasible() == renamed.is_feasible()


def test_removing_evidence_only_widens_a_feasible_query():
    system = QuantityConstraintSystem()
    system.add_variable(QuantityVariable("quantity", "each", DISCRETE))
    system.add_constraint(
        "opening-upper",
        {"quantity": 1},
        ConstraintRelation.AT_MOST,
        10,
    )
    system.add_constraint(
        "later-lower",
        {"quantity": 1},
        ConstraintRelation.AT_LEAST,
        4,
    )
    complete = ConstraintGraphSnapshot.capture(2, system)
    reduced = ConstraintGraphSnapshot(
        1,
        complete.variables,
        tuple(
            constraint
            for constraint in complete.constraints
            if constraint.constraint_id != "later-lower"
        ),
    )
    query = ExpressionBoundsQuery(ExactLinearExpression({"quantity": 1}))
    evaluator = ConstraintQueryEvaluator()

    before_removal = evaluator.evaluate(complete, query)
    after_removal = evaluator.evaluate(reduced, query)

    assert _bounds_pair(before_removal.bounds) == (Fraction(4), Fraction(10))
    assert _bounds_pair(after_removal.bounds) == (Fraction(0), Fraction(10))


def test_reordering_independent_facts_does_not_change_a_query():
    system, primary = _bounded_variable_system()
    snapshot = ConstraintGraphSnapshot.capture(1, system)
    reordered = ConstraintGraphSnapshot(
        1,
        tuple(reversed(snapshot.variables)),
        tuple(reversed(snapshot.constraints)),
    )
    query = ExpressionBoundsQuery(ExactLinearExpression({primary: 1}))
    evaluator = ConstraintQueryEvaluator()

    original_answer = evaluator.evaluate(snapshot, query)
    reordered_answer = evaluator.evaluate(reordered, query)

    assert original_answer.bounds == reordered_answer.bounds
    assert original_answer.status == reordered_answer.status


def test_compiled_snapshot_is_not_mutated_by_later_recorded_evidence():
    holding = HoldingKey("BAT-ONE", "BIN-ONE", "each")
    first_moment = datetime(2026, 8, 1, tzinfo=timezone.utc)
    second_moment = datetime(2026, 8, 2, tzinfo=timezone.utc)
    timeline = ProcessQuantityTimeline()
    timeline.record(ObservationEvent(
        holding,
        DISCRETE,
        QuantityObservation(
            "OBS-opening-range",
            lower=0,
            upper=10,
            basis=ObservationBasis.ESTIMATED,
        ),
        first_moment,
        first_moment,
    ))
    frozen_snapshot = timeline.compile()

    timeline.record(ObservationEvent(
        holding,
        DISCRETE,
        QuantityObservation.exact(
            "OBS-later-count",
            4,
            basis=ObservationBasis.COUNTED,
        ),
        second_moment,
        second_moment,
    ))
    fresh_snapshot = timeline.compile()

    assert _bounds_pair(frozen_snapshot.current_bounds(holding)) == (
        Fraction(0),
        Fraction(10),
    )
    assert _bounds_pair(fresh_snapshot.current_bounds(holding)) == (
        Fraction(4),
        Fraction(4),
    )


def test_counterfactual_overlay_does_not_mutate_its_base_snapshot():
    system = QuantityConstraintSystem()
    system.add_variable(QuantityVariable("quantity", "each", DISCRETE))
    system.add_constraint(
        "opening-upper",
        {"quantity": 1},
        ConstraintRelation.AT_MOST,
        10,
    )
    snapshot = ConstraintGraphSnapshot.capture(7, system)
    overlay = ConstraintOverlay(constraints=(LinearConstraint(
        "hypothetical-lower",
        (("quantity", Fraction(1)),),
        ConstraintRelation.AT_LEAST,
        Fraction(4),
    ),))
    query = ExpressionBoundsQuery(ExactLinearExpression({"quantity": 1}))
    evaluator = ConstraintQueryEvaluator()
    original_snapshot = (
        snapshot.revision,
        snapshot.variables,
        snapshot.constraints,
    )
    original_overlay = (overlay.variables, overlay.constraints)

    base_before = evaluator.evaluate(snapshot, query)
    hypothetical = evaluator.evaluate(snapshot, query, overlay=overlay)
    base_after = evaluator.evaluate(snapshot, query)

    assert _bounds_pair(base_before.bounds) == (Fraction(0), Fraction(10))
    assert _bounds_pair(hypothetical.bounds) == (Fraction(4), Fraction(10))
    assert base_after == base_before
    assert (
        snapshot.revision,
        snapshot.variables,
        snapshot.constraints,
    ) == original_snapshot
    assert (overlay.variables, overlay.constraints) == original_overlay
