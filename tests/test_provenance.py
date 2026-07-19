"""Worked scenarios for the persistence-free provenance kernel."""

from decimal import Decimal

import pytest

from inventorius.provenance import (
    AllocationSemantics,
    AssemblyRun,
    ComponentUse,
    ConsumedHolding,
    GeneralSolverRequired,
    HoldingReference,
    MaterialLoss,
    ProducedHolding,
    ProvenanceNetwork,
    Quantity,
    TransformationRun,
)


UNIT = "unit"


def consumed(batch_id: str, amount: int, location: str = "BIN000001"):
    return ConsumedHolding(
        HoldingReference(batch_id, location),
        Quantity(amount, UNIT),
    )


def produced(batch_id: str, amount: int, location: str = "BIN000002"):
    return ProducedHolding(batch_id, location, Quantity(amount, UNIT))


@pytest.fixture
def divided_pool():
    network = ProvenanceNetwork()
    network.add_run(TransformationRun(
        run_id="RUN-pool-and-divide",
        consumed=(consumed("BAT-A", 8), consumed("BAT-B", 2)),
        produced=(
            produced("BAT-C1", 7),
            produced("BAT-C2", 2),
            produced("BAT-C3", 1),
        ),
    ))
    return network


def assert_bounds(actual, minimum: int | str, maximum: int | str):
    assert actual.minimum == Decimal(str(minimum))
    assert actual.maximum == Decimal(str(maximum))
    assert actual.unit == UNIT


def test_more_sibling_outputs_tighten_uncertain_provenance(divided_pool):
    assert_bounds(
        divided_pool.contribution_bounds("BAT-A", ["BAT-C1"]),
        5,
        7,
    )
    assert_bounds(
        divided_pool.contribution_bounds("BAT-B", ["BAT-C1"]),
        0,
        2,
    )
    assert_bounds(
        divided_pool.contribution_bounds("BAT-A", ["BAT-C1", "BAT-C2"]),
        7,
        8,
    )
    assert_bounds(
        divided_pool.contribution_bounds("BAT-B", ["BAT-C1", "BAT-C2"]),
        1,
        2,
    )


def test_complete_partition_restores_exact_ancestry(divided_pool):
    assert_bounds(
        divided_pool.contribution_bounds(
            "BAT-A", ["BAT-C1", "BAT-C2", "BAT-C3"]
        ),
        8,
        8,
    )
    assert_bounds(
        divided_pool.contribution_bounds(
            "BAT-B", ["BAT-C1", "BAT-C2", "BAT-C3"]
        ),
        2,
        2,
    )


def test_partial_consumption_withdraws_only_the_used_amount():
    network = ProvenanceNetwork()
    network.add_run(TransformationRun(
        run_id="RUN-use-three-from-a-holding-of-ten",
        consumed=(consumed("BAT-A", 3),),
        produced=(produced("BAT-B", 3),),
    ))

    assert_bounds(network.contribution_bounds("BAT-A", ["BAT-B"]), 3, 3)


def test_explicit_loss_participates_in_conservation_and_lineage():
    network = ProvenanceNetwork()
    network.add_run(TransformationRun(
        run_id="RUN-with-process-loss",
        consumed=(consumed("BAT-A", 8), consumed("BAT-B", 2)),
        produced=(produced("BAT-C", 9),),
        losses=(
            MaterialLoss(
                "LOSS-evaporation",
                "evaporation",
                Quantity(1, UNIT),
            ),
        ),
    ))

    assert_bounds(network.contribution_bounds("BAT-A", ["BAT-C"]), 7, 8)
    assert_bounds(network.contribution_bounds("BAT-B", ["BAT-C"]), 1, 2)
    assert_bounds(
        network.contribution_bounds("BAT-A", ["LOSS-evaporation"]),
        0,
        1,
    )
    assert_bounds(
        network.contribution_bounds(
            "BAT-A", ["BAT-C", "LOSS-evaporation"]
        ),
        8,
        8,
    )


def test_homogeneous_blend_has_exact_proportional_lineage():
    network = ProvenanceNetwork()
    network.add_run(TransformationRun(
        run_id="RUN-blend-and-bottle",
        consumed=(
            ConsumedHolding(
                HoldingReference("BAT-A", "BIN000001"),
                Quantity(8, "liter"),
            ),
            ConsumedHolding(
                HoldingReference("BAT-B", "BIN000001"),
                Quantity(2, "liter"),
            ),
        ),
        produced=(
            ProducedHolding("BAT-C1", "BIN000002", Quantity(4, "liter")),
            ProducedHolding("BAT-C2", "BIN000002", Quantity(6, "liter")),
        ),
        allocation=AllocationSemantics.HOMOGENEOUS_BLEND,
    ))

    bounds = network.contribution_bounds("BAT-A", ["BAT-C1"])
    assert bounds.minimum == Decimal("3.2")
    assert bounds.maximum == Decimal("3.2")
    assert bounds.unit == "liter"

    bounds = network.contribution_bounds("BAT-B", ["BAT-C2"])
    assert bounds.minimum == Decimal("1.2")
    assert bounds.maximum == Decimal("1.2")
    assert bounds.unit == "liter"


def test_structural_assembly_preserves_component_roles_and_native_units():
    network = ProvenanceNetwork()
    network.add_assembly(AssemblyRun(
        run_id="RUN-assemble-controller",
        components=(
            ComponentUse(
                HoldingReference("BAT-BOARD", "BIN000010"),
                Quantity(1, "item"),
                "controller board",
            ),
            ComponentUse(
                HoldingReference("BAT-SCREW", "BIN000011"),
                Quantity(4, "item"),
                "case fastener",
            ),
            ComponentUse(
                HoldingReference("BAT-WIRE", "BIN000012"),
                Quantity(20, "centimeter"),
                "power lead",
            ),
        ),
        produced=ProducedHolding(
            "BAT-CONTROLLER",
            "BIN000020",
            Quantity(1, "item"),
        ),
    ))

    screws = network.direct_component_bounds("BAT-SCREW", "BAT-CONTROLLER")
    assert screws.minimum == Decimal(4)
    assert screws.maximum == Decimal(4)
    assert screws.unit == "item"
    wire = network.direct_component_bounds("BAT-WIRE", "BAT-CONTROLLER")
    assert wire.minimum == Decimal(20)
    assert wire.maximum == Decimal(20)
    assert wire.unit == "centimeter"


def test_full_downstream_recombination_restores_exact_ancestry(divided_pool):
    divided_pool.add_run(TransformationRun(
        run_id="RUN-recombine-all",
        consumed=(
            consumed("BAT-C1", 7, "BIN000002"),
            consumed("BAT-C2", 2, "BIN000002"),
            consumed("BAT-C3", 1, "BIN000002"),
        ),
        produced=(produced("BAT-D", 10, "BIN000003"),),
    ))

    assert_bounds(
        divided_pool.contribution_bounds("BAT-A", ["BAT-D"]),
        8,
        8,
    )
    assert_bounds(
        divided_pool.contribution_bounds("BAT-B", ["BAT-D"]),
        2,
        2,
    )


def test_global_solver_resolves_uncertain_intermediate_path(divided_pool):
    divided_pool.add_run(TransformationRun(
        run_id="RUN-pool-again",
        consumed=(
            consumed("BAT-C1", 7, "BIN000002"),
            consumed("BAT-X", 3, "BIN000002"),
        ),
        produced=(
            produced("BAT-D1", 5, "BIN000003"),
            produced("BAT-D2", 5, "BIN000003"),
        ),
    ))

    assert_bounds(
        divided_pool.contribution_bounds("BAT-A", ["BAT-D1"]),
        0,
        5,
    )
    assert_bounds(
        divided_pool.contribution_bounds("BAT-A", ["BAT-D1", "BAT-D2"]),
        5,
        7,
    )


def test_global_solver_matches_exhaustive_small_integer_histories():
    for source_amount in range(1, 5):
        for other_amount in range(1, 4):
            first_total = source_amount + other_amount
            for intermediate_amount in range(1, first_total):
                for added_amount in range(1, 4):
                    second_total = intermediate_amount + added_amount
                    for target_amount in range(1, second_total):
                        network = ProvenanceNetwork()
                        network.add_run(TransformationRun(
                            run_id="RUN-first",
                            consumed=(
                                consumed("BAT-A", source_amount),
                                consumed("BAT-B", other_amount),
                            ),
                            produced=(
                                produced("BAT-C1", intermediate_amount),
                                produced(
                                    "BAT-C2",
                                    first_total - intermediate_amount,
                                ),
                            ),
                        ))
                        network.add_run(TransformationRun(
                            run_id="RUN-second",
                            consumed=(
                                consumed("BAT-C1", intermediate_amount),
                                consumed("BAT-X", added_amount),
                            ),
                            produced=(
                                produced("BAT-D1", target_amount),
                                produced(
                                    "BAT-D2",
                                    second_total - target_amount,
                                ),
                            ),
                        ))

                        feasible = []
                        first_lower = max(
                            0,
                            source_amount
                            + intermediate_amount
                            - first_total,
                        )
                        first_upper = min(
                            source_amount,
                            intermediate_amount,
                        )
                        for source_in_intermediate in range(
                            first_lower,
                            first_upper + 1,
                        ):
                            second_lower = max(
                                0,
                                source_in_intermediate
                                + target_amount
                                - second_total,
                            )
                            second_upper = min(
                                source_in_intermediate,
                                target_amount,
                            )
                            feasible.extend(range(second_lower, second_upper + 1))

                        actual = network.contribution_bounds("BAT-A", ["BAT-D1"])
                        assert actual.minimum == min(feasible)
                        assert actual.maximum == max(feasible)


def test_mixed_multistage_semantics_wait_for_general_linear_solver():
    network = ProvenanceNetwork()
    network.add_run(TransformationRun(
        run_id="RUN-homogeneous",
        consumed=(consumed("BAT-A", 8), consumed("BAT-B", 2)),
        produced=(produced("BAT-C", 7), produced("BAT-C2", 3)),
        allocation=AllocationSemantics.HOMOGENEOUS_BLEND,
    ))
    network.add_run(TransformationRun(
        run_id="RUN-uncertain",
        consumed=(consumed("BAT-C", 7), consumed("BAT-X", 3)),
        produced=(produced("BAT-D1", 5), produced("BAT-D2", 5)),
    ))

    with pytest.raises(GeneralSolverRequired, match="mixed allocation semantics"):
        network.contribution_bounds("BAT-A", ["BAT-D1"])


def test_conserved_pool_rejects_unit_or_quantity_mismatch():
    network = ProvenanceNetwork()

    with pytest.raises(ValueError, match="preserve total"):
        network.add_run(TransformationRun(
            run_id="RUN-loss-not-yet-supported",
            consumed=(consumed("BAT-A", 8),),
            produced=(produced("BAT-C", 7),),
        ))

    with pytest.raises(ValueError, match="one compatible unit"):
        network.add_run(TransformationRun(
            run_id="RUN-conversion-not-yet-supported",
            consumed=(consumed("BAT-A", 8),),
            produced=(
                ProducedHolding("BAT-C", "BIN000002", Quantity(8, "kg")),
            ),
        ))
