"""Independent physical checks for the bounded finite-history oracle."""

import pytest

from tests.solver.reference_oracle import (
    EventGroup,
    FiniteHistoryOracle,
    LEDAllocationScenario,
    NoFeasibleWorlds,
)


def assert_bounds(bounds, minimum, maximum):
    assert bounds.minimum == minimum
    assert bounds.maximum == maximum
    assert bounds.minimum_witness is not None
    assert bounds.maximum_witness is not None


def test_oracle_returns_exact_worlds_bounds_and_predicate_answers():
    oracle = FiniteHistoryOracle(
        {
            "x": range(3),
            "y": range(3),
        },
        (
            EventGroup.one(
                "total-is-two",
                lambda world: world["x"] + world["y"] == 2,
            ),
            EventGroup.one("x-at-most-one", lambda world: world["x"] <= 1),
        ),
    )

    worlds = oracle.feasible_worlds()
    assert [dict(world) for world in worlds] == [
        {"x": 0, "y": 2},
        {"x": 1, "y": 1},
    ]
    assert oracle.enumerated_world_count == 9

    x_bounds = oracle.expression_bounds(lambda world: world["x"])
    assert_bounds(x_bounds, 0, 1)
    assert x_bounds.minimum_witness["x"] == 0
    assert x_bounds.maximum_witness["x"] == 1

    total_bounds = oracle.expression_bounds(
        lambda world: world["x"] + world["y"]
    )
    assert_bounds(total_bounds, 2, 2)
    assert total_bounds.exact

    zero = oracle.evaluate_predicate(lambda world: world["x"] == 0)
    assert zero.possible
    assert not zero.guaranteed
    assert zero.satisfying_witness["x"] == 0
    assert zero.counterexample_witness["x"] == 1

    bounded = oracle.evaluate_predicate(lambda world: world["x"] <= 1)
    assert bounded.possible
    assert bounded.guaranteed
    assert bounded.counterexample_witness is None


def test_expression_and_predicate_queries_reject_an_infeasible_history():
    oracle = FiniteHistoryOracle(
        {"quantity": range(3)},
        (
            EventGroup.one("at-most-one", lambda world: world["quantity"] <= 1),
            EventGroup.one("at-least-two", lambda world: world["quantity"] >= 2),
        ),
    )

    assert not oracle.is_feasible()
    assert oracle.feasible_worlds() == ()
    with pytest.raises(NoFeasibleWorlds):
        oracle.expression_bounds(lambda world: world["quantity"])
    with pytest.raises(NoFeasibleWorlds):
        oracle.evaluate_predicate(lambda world: world["quantity"] == 1)


def test_corrected_led_scenario_keeps_individual_parts_vague_but_sum_sharp():
    scenario = LEDAllocationScenario(
        opening_red=25,
        opening_blue=25,
        part_a_size=24,
        part_b_size=25,
    )
    oracle = scenario.oracle()

    assert oracle.enumerated_world_count == 650
    assert len(oracle.feasible_worlds()) == 50
    assert_bounds(
        oracle.expression_bounds(lambda world: world["red_in_a"]),
        0,
        24,
    )
    assert_bounds(
        oracle.expression_bounds(lambda world: world["red_in_b"]),
        0,
        25,
    )
    aggregate = oracle.expression_bounds(scenario.red_used)
    assert_bounds(aggregate, 24, 25)
    assert scenario.red_used(aggregate.minimum_witness) == 24
    assert scenario.red_used(aggregate.maximum_witness) == 25


def test_later_blue_observation_sharpens_only_the_aggregate_query():
    scenario = LEDAllocationScenario(25, 25, 24, 25)
    oracle = scenario.oracle(observed_remaining_blue=1)

    assert len(oracle.feasible_worlds()) == 25
    assert_bounds(
        oracle.expression_bounds(lambda world: world["red_in_a"]),
        0,
        24,
    )
    assert_bounds(
        oracle.expression_bounds(lambda world: world["red_in_b"]),
        1,
        25,
    )
    assert_bounds(oracle.expression_bounds(scenario.red_used), 25, 25)

    for world in oracle.feasible_worlds():
        assert scenario.remaining_blue(world) == 1
        assert scenario.remaining_red(world) == 0


def test_small_led_worlds_match_closed_form_aggregate_bounds():
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
                    total_used = part_a_size + part_b_size
                    expected_minimum = max(0, total_used - opening_blue)
                    expected_maximum = min(total_used, opening_red)

                    bounds = scenario.oracle().expression_bounds(
                        scenario.red_used
                    )
                    assert_bounds(
                        bounds,
                        expected_minimum,
                        expected_maximum,
                    )
                    checked += 1

    assert checked == 425


def test_small_blue_observations_determine_aggregate_red_without_overclaiming():
    for opening_red in range(1, 5):
        for opening_blue in range(1, 5):
            total_available = opening_red + opening_blue
            for total_used in range(1, total_available + 1):
                scenario = LEDAllocationScenario(
                    opening_red,
                    opening_blue,
                    total_used,
                    0,
                )
                minimum_blue_used = max(0, total_used - opening_red)
                maximum_blue_used = min(total_used, opening_blue)
                for blue_used in range(
                    minimum_blue_used,
                    maximum_blue_used + 1,
                ):
                    observed_remaining = opening_blue - blue_used
                    oracle = scenario.oracle(
                        observed_remaining_blue=observed_remaining
                    )
                    expected_red_used = total_used - blue_used
                    assert_bounds(
                        oracle.expression_bounds(scenario.red_used),
                        expected_red_used,
                        expected_red_used,
                    )


def test_exhaustive_event_subsets_find_the_specific_counterfactual_conflict():
    oracle = FiniteHistoryOracle(
        {"quantity": range(6)},
        (
            EventGroup.one("base-opening", lambda world: world["quantity"] <= 5),
            EventGroup.one("process-x", lambda world: world["quantity"] >= 2),
            EventGroup(
                "process-y",
                (
                    lambda world: world["quantity"] >= 0,
                    lambda world: world["quantity"] <= 3,
                ),
            ),
            EventGroup.one("process-z", lambda world: world["quantity"] % 2 == 0),
            EventGroup.one("observation-a", lambda world: world["quantity"] == 4),
        ),
    )
    candidates = (
        "process-x",
        "process-y",
        "process-z",
        "observation-a",
    )

    assert oracle.deletion_minimal_conflicts(
        candidates,
        fixed_group_ids=("base-opening",),
    ) == (("process-y", "observation-a"),)
    assert oracle.is_deletion_minimal_conflict(
        ("process-y", "observation-a"),
        fixed_group_ids=("base-opening",),
    )

    included = ("base-opening", *candidates)
    assert oracle.removal_restores_feasibility("process-y", included)
    assert oracle.removal_restores_feasibility("observation-a", included)
    assert not oracle.removal_restores_feasibility("process-x", included)
    assert not oracle.removal_restores_feasibility("process-z", included)


def test_removal_does_not_claim_to_restore_an_already_feasible_history():
    oracle = FiniteHistoryOracle(
        {"quantity": range(4)},
        (
            EventGroup.one("at-least-one", lambda world: world["quantity"] >= 1),
            EventGroup.one("at-most-three", lambda world: world["quantity"] <= 3),
        ),
    )

    assert oracle.is_feasible()
    assert not oracle.removal_restores_feasibility("at-least-one")


def test_already_conflicted_frozen_graph_is_not_blamed_on_overlay():
    oracle = FiniteHistoryOracle(
        {"quantity": range(4)},
        (
            EventGroup.one("base-low", lambda world: world["quantity"] <= 1),
            EventGroup.one("base-high", lambda world: world["quantity"] >= 2),
            EventGroup.one(
                "proposed-process",
                lambda world: world["quantity"] == 3,
            ),
        ),
    )

    assert oracle.deletion_minimal_conflicts(
        ("proposed-process",),
        fixed_group_ids=("base-low", "base-high"),
    ) == ((),)
