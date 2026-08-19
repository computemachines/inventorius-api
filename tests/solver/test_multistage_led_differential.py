"""Differential checks for correlated provenance across two process stages.

The production graph below is deliberately assembled without using equations
from the finite-world oracle.  It models conservation and flow at each process
boundary, then asks both local and end-to-end questions of that one graph.
"""

from fractions import Fraction

from inventorius.constraint_queries import (
    ConstraintGraphSnapshot,
    ConstraintOverlay,
    ConstraintQueryEvaluator,
    ExactLinearExpression,
    ExpressionBoundsQuery,
    QueryStatus,
)
from inventorius.quantity_constraints import (
    ConstraintRelation,
    LinearConstraint,
    QuantityDomain,
    QuantityVariable,
)
from tests.solver.reference_oracle import TwoStageLEDAssemblyScenario


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


def _part_variable(index: int, quantity: str) -> str:
    return f"part:{index}:{quantity}"


def _two_stage_snapshot(
    scenario: TwoStageLEDAssemblyScenario,
    *,
    revision: int = 1,
) -> ConstraintGraphSnapshot:
    """Describe the two physical process stages as local conservation facts."""

    variable_ids = [
        "source:red-remaining",
        "source:blue-remaining",
        "final:red",
        "final:blue",
    ]
    constraints = []

    opening_red = {"source:red-remaining": 1}
    opening_blue = {"source:blue-remaining": 1}
    final_red = {"final:red": 1}
    final_blue = {"final:blue": 1}

    for index, (part_size, final_draw) in enumerate(
        zip(scenario.part_sizes, scenario.final_draws)
    ):
        red_in = _part_variable(index, "red-in")
        blue_in = _part_variable(index, "blue-in")
        red_to_final = _part_variable(index, "red-to-final")
        blue_to_final = _part_variable(index, "blue-to-final")
        red_left = _part_variable(index, "red-left")
        blue_left = _part_variable(index, "blue-left")

        variable_ids.extend((
            red_in,
            blue_in,
            red_to_final,
            blue_to_final,
            red_left,
            blue_left,
        ))
        opening_red[red_in] = 1
        opening_blue[blue_in] = 1
        final_red[red_to_final] = -1
        final_blue[blue_to_final] = -1

        constraints.extend((
            _fact(
                f"part:{index}:input-total",
                {red_in: 1, blue_in: 1},
                ConstraintRelation.EQUAL,
                part_size,
            ),
            _fact(
                f"part:{index}:red-split",
                {red_in: 1, red_to_final: -1, red_left: -1},
                ConstraintRelation.EQUAL,
                0,
            ),
            _fact(
                f"part:{index}:blue-split",
                {blue_in: 1, blue_to_final: -1, blue_left: -1},
                ConstraintRelation.EQUAL,
                0,
            ),
            _fact(
                f"part:{index}:final-draw-total",
                {red_to_final: 1, blue_to_final: 1},
                ConstraintRelation.EQUAL,
                final_draw,
            ),
        ))

    constraints.extend((
        _fact(
            "opening:red-conservation",
            opening_red,
            ConstraintRelation.EQUAL,
            scenario.opening_red,
        ),
        _fact(
            "opening:blue-conservation",
            opening_blue,
            ConstraintRelation.EQUAL,
            scenario.opening_blue,
        ),
        _fact(
            "final:red-provenance",
            final_red,
            ConstraintRelation.EQUAL,
            0,
        ),
        _fact(
            "final:blue-provenance",
            final_blue,
            ConstraintRelation.EQUAL,
            0,
        ),
    ))

    return ConstraintGraphSnapshot(
        revision,
        tuple(_variable(variable_id) for variable_id in variable_ids),
        tuple(constraints),
    )


def _outside_blue_fact(
    scenario: TwoStageLEDAssemblyScenario,
    observed_outside_blue: int,
) -> LinearConstraint:
    coefficients = {"source:blue-remaining": 1}
    coefficients.update({
        _part_variable(index, "blue-left"): 1
        for index in range(scenario.part_count)
    })
    return _fact(
        "observation:outside-blue",
        coefficients,
        ConstraintRelation.EQUAL,
        observed_outside_blue,
    )


def _bounds(
    snapshot: ConstraintGraphSnapshot,
    coefficients: dict[str, int],
    *,
    overlay: ConstraintOverlay | None = None,
) -> tuple[Fraction, Fraction]:
    result = ConstraintQueryEvaluator().evaluate(
        snapshot,
        ExpressionBoundsQuery(ExactLinearExpression(coefficients)),
        overlay=overlay,
    )
    assert result.status == QueryStatus.SOLVED
    assert result.bounds is not None
    assert result.bounds.minimum is not None
    assert result.bounds.maximum is not None
    return result.bounds.minimum, result.bounds.maximum


def _oracle_bounds(oracle, expression) -> tuple[Fraction, Fraction]:
    answer = oracle.expression_bounds(expression)
    return Fraction(answer.minimum), Fraction(answer.maximum)


def _canonical_scenario() -> TwoStageLEDAssemblyScenario:
    return TwoStageLEDAssemblyScenario(
        opening_red=12,
        opening_blue=12,
        part_sizes=(8, 7, 6),
        final_draws=(7, 7, 6),
    )


def test_two_stage_queries_match_enumeration_and_keep_local_answers_vague():
    scenario = _canonical_scenario()
    base_oracle = scenario.oracle()
    observed_oracle = scenario.oracle(observed_outside_blue=1)
    base = _two_stage_snapshot(scenario, revision=80)
    observation = _outside_blue_fact(scenario, 1)
    observed = ConstraintGraphSnapshot(
        81,
        base.variables,
        (*base.constraints, observation),
    )

    assert base_oracle.enumerated_world_count == 1008
    assert len(base_oracle.feasible_worlds()) == 340
    assert len(observed_oracle.feasible_worlds()) == 86

    base_final_red = _bounds(base, {"final:red": 1})
    observed_final_red = _bounds(observed, {"final:red": 1})
    final_red_contributions = {
        _part_variable(index, "red-to-final"): 1
        for index in range(scenario.part_count)
    }
    assert base_final_red == _oracle_bounds(
        base_oracle,
        scenario.red_final,
    ) == (Fraction(8), Fraction(12))
    assert _bounds(base, {"final:blue": 1}) == _oracle_bounds(
        base_oracle,
        scenario.blue_final,
    ) == (Fraction(8), Fraction(12))
    assert _bounds(
        base,
        {"final:red": 1, "final:blue": 1},
    ) == (Fraction(20), Fraction(20))
    assert observed_final_red == _oracle_bounds(
        observed_oracle,
        scenario.red_final,
    ) == (Fraction(9), Fraction(9))
    assert _bounds(base, final_red_contributions) == base_final_red
    assert _bounds(observed, final_red_contributions) == observed_final_red
    assert _bounds(observed, {"final:blue": 1}) == _oracle_bounds(
        observed_oracle,
        scenario.blue_final,
    ) == (Fraction(11), Fraction(11))
    assert _bounds(
        observed,
        {"final:red": 1, "final:blue": 1},
    ) == (Fraction(20), Fraction(20))

    for index, (part_size, final_draw) in enumerate(
        zip(scenario.part_sizes, scenario.final_draws)
    ):
        red_in = {_part_variable(index, "red-in"): 1}
        red_to_final = {_part_variable(index, "red-to-final"): 1}
        blue_in = {_part_variable(index, "blue-in"): 1}
        blue_to_final = {_part_variable(index, "blue-to-final"): 1}

        expected_red_in = _oracle_bounds(
            base_oracle,
            lambda world, selected=index: scenario.red_in_part(
                world,
                selected,
            ),
        )
        expected_red_to_final = _oracle_bounds(
            base_oracle,
            lambda world, selected=index: scenario.red_to_final_from_part(
                world,
                selected,
            ),
        )
        expected_blue_in = _oracle_bounds(
            base_oracle,
            lambda world, selected=index: scenario.blue_in_part(
                world,
                selected,
            ),
        )
        expected_blue_to_final = _oracle_bounds(
            base_oracle,
            lambda world, selected=index: scenario.blue_to_final_from_part(
                world,
                selected,
            ),
        )
        assert _bounds(base, red_in) == expected_red_in == (
            Fraction(0),
            Fraction(part_size),
        )
        assert _bounds(observed, red_in) == _oracle_bounds(
            observed_oracle,
            lambda world, selected=index: scenario.red_in_part(
                world,
                selected,
            ),
        ) == expected_red_in
        assert _bounds(base, red_to_final) == expected_red_to_final == (
            Fraction(0),
            Fraction(final_draw),
        )
        assert _bounds(observed, red_to_final) == _oracle_bounds(
            observed_oracle,
            lambda world, selected=index: scenario.red_to_final_from_part(
                world,
                selected,
            ),
        ) == expected_red_to_final
        assert _bounds(base, blue_in) == expected_blue_in == (
            Fraction(0),
            Fraction(part_size),
        )
        assert _bounds(observed, blue_in) == _oracle_bounds(
            observed_oracle,
            lambda world, selected=index: scenario.blue_in_part(
                world,
                selected,
            ),
        ) == expected_blue_in
        assert _bounds(base, blue_to_final) == expected_blue_to_final == (
            Fraction(0),
            Fraction(final_draw),
        )
        assert _bounds(observed, blue_to_final) == _oracle_bounds(
            observed_oracle,
            lambda world, selected=index: scenario.blue_to_final_from_part(
                world,
                selected,
            ),
        ) == expected_blue_to_final

    red_in_all_parts = {
        _part_variable(index, "red-in"): 1
        for index in range(scenario.part_count)
    }
    assert _bounds(base, red_in_all_parts) == _oracle_bounds(
        base_oracle,
        scenario.red_in_parts,
    ) == (Fraction(9), Fraction(12))
    assert _bounds(observed, red_in_all_parts) == _oracle_bounds(
        observed_oracle,
        scenario.red_in_parts,
    ) == (Fraction(9), Fraction(10))


def test_outside_observation_preserves_correlation_and_revision_history():
    scenario = _canonical_scenario()
    base = _two_stage_snapshot(scenario, revision=80)
    observation = _outside_blue_fact(scenario, 1)
    overlay = ConstraintOverlay(constraints=(observation,))
    observed = ConstraintGraphSnapshot(
        81,
        base.variables,
        (*base.constraints, observation),
    )
    outside_blue = {"source:blue-remaining": 1}
    outside_blue.update({
        _part_variable(index, "blue-left"): 1
        for index in range(scenario.part_count)
    })
    outside_red = {"source:red-remaining": 1}
    outside_red.update({
        _part_variable(index, "red-left"): 1
        for index in range(scenario.part_count)
    })

    before = _bounds(base, {"final:red": 1})
    appended = _bounds(observed, {"final:red": 1})
    hypothetical = _bounds(base, {"final:red": 1}, overlay=overlay)
    after = _bounds(base, {"final:red": 1})

    assert before == after == (Fraction(8), Fraction(12))
    assert appended == hypothetical == (Fraction(9), Fraction(9))
    assert base.revision == 80
    assert observed.revision == 81

    source_blue = _bounds(observed, {"source:blue-remaining": 1})
    part_blue_left = [
        _bounds(observed, {_part_variable(index, "blue-left"): 1})
        for index in range(scenario.part_count)
    ]
    direct_outside = _bounds(observed, outside_blue)
    hypothetical_outside = _bounds(base, outside_blue, overlay=overlay)
    oracle = scenario.oracle(observed_outside_blue=1)

    assert source_blue == (Fraction(0), Fraction(1))
    assert part_blue_left == [
        (Fraction(0), Fraction(1)),
        (Fraction(0), Fraction(0)),
        (Fraction(0), Fraction(0)),
    ]
    assert direct_outside == _oracle_bounds(
        oracle,
        scenario.outside_blue,
    ) == (Fraction(1), Fraction(1))
    assert hypothetical_outside == direct_outside
    assert sum(bound[0] for bound in (source_blue, *part_blue_left)) == 0
    assert sum(bound[1] for bound in (source_blue, *part_blue_left)) == 2

    source_red = _bounds(observed, {"source:red-remaining": 1})
    part_red_left = [
        _bounds(observed, {_part_variable(index, "red-left"): 1})
        for index in range(scenario.part_count)
    ]
    direct_outside_red = _bounds(observed, outside_red)

    assert source_red == (Fraction(2), Fraction(3))
    assert part_red_left == [
        (Fraction(0), Fraction(1)),
        (Fraction(0), Fraction(0)),
        (Fraction(0), Fraction(0)),
    ]
    assert direct_outside_red == _oracle_bounds(
        oracle,
        scenario.outside_red,
    ) == (Fraction(3), Fraction(3))
    assert sum(bound[0] for bound in (source_red, *part_red_left)) == 2
    assert sum(bound[1] for bound in (source_red, *part_red_left)) == 4


def test_generated_small_two_stage_histories_match_independent_enumeration():
    checked = 0
    for opening_red in range(3):
        for opening_blue in range(3):
            available = opening_red + opening_blue
            for part_a_size in range(available + 1):
                for part_b_size in range(available - part_a_size + 1):
                    for draw_a in range(part_a_size + 1):
                        for draw_b in range(part_b_size + 1):
                            scenario = TwoStageLEDAssemblyScenario(
                                opening_red,
                                opening_blue,
                                (part_a_size, part_b_size),
                                (draw_a, draw_b),
                            )
                            expected = scenario.oracle().expression_bounds(
                                scenario.red_final
                            )
                            actual = _bounds(
                                _two_stage_snapshot(scenario),
                                {"final:red": 1},
                            )

                            assert actual == (
                                Fraction(expected.minimum),
                                Fraction(expected.maximum),
                            )
                            checked += 1

    assert checked == 196
