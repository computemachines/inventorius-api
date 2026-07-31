"""Versioned, lossless persistence boundary for provenance constraints."""

import json
from dataclasses import FrozenInstanceError
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
    Quantity,
    TransformationRun,
)
from inventorius.provenance_serialization import (
    CODEC_NAME,
    CODEC_VERSION,
    ProvenanceConstraintSet,
    provenance_network_from_document,
)


def consumed(
    batch_id: str,
    amount: str,
    unit: str = "kg",
    location_id: str = "BIN-INPUT",
) -> ConsumedHolding:
    return ConsumedHolding(
        HoldingReference(batch_id, location_id),
        Quantity(Decimal(amount), unit),
    )


def produced(
    batch_id: str,
    amount: str,
    unit: str = "kg",
    location_id: str = "BIN-OUTPUT",
) -> ProducedHolding:
    return ProducedHolding(
        batch_id,
        location_id,
        Quantity(Decimal(amount), unit),
    )


def worked_constraint_set() -> ProvenanceConstraintSet:
    return ProvenanceConstraintSet(
        transformations=(
            TransformationRun(
                run_id="RUN-homogeneous",
                consumed=(
                    consumed("BAT-A", "8.00"),
                    consumed("BAT-B", "2.00"),
                ),
                produced=(
                    produced("BAT-C", "7.00"),
                    produced("BAT-C2", "3.00"),
                ),
                allocation=AllocationSemantics.HOMOGENEOUS_BLEND,
            ),
            TransformationRun(
                run_id="RUN-uncertain",
                consumed=(
                    consumed("BAT-C", "7.00", location_id="BIN-MIX"),
                    consumed("BAT-X", "3.00", location_id="BIN-MIX"),
                ),
                produced=(
                    produced("BAT-D1", "5.00", location_id="BIN-FINAL"),
                    produced("BAT-D2", "5.00", location_id="BIN-FINAL"),
                ),
            ),
            TransformationRun(
                run_id="RUN-with-loss",
                consumed=(consumed("BAT-RAW", "1.2300", "liter"),),
                produced=(produced("BAT-PRODUCT", "1.2000", "liter"),),
                losses=(
                    MaterialLoss(
                        "LOSS-EVAPORATION",
                        "evaporation",
                        Quantity(Decimal("0.0300"), "liter"),
                    ),
                ),
            ),
        ),
        assemblies=(
            AssemblyRun(
                run_id="RUN-assembly",
                components=(
                    ComponentUse(
                        HoldingReference("BAT-BOARD", "BIN-PARTS"),
                        Quantity(Decimal("1.0"), "item"),
                        "controller board",
                    ),
                    ComponentUse(
                        HoldingReference("BAT-WIRE", "BIN-WIRE"),
                        Quantity(Decimal("20.00"), "centimeter"),
                        "power lead",
                    ),
                ),
                produced=produced(
                    "BAT-CONTROLLER",
                    "1.0",
                    "item",
                    "BIN-ASSEMBLY",
                ),
            ),
        ),
    )


def test_constraint_document_is_json_safe_versioned_and_lossless():
    constraints = worked_constraint_set()

    document = constraints.to_document()
    json_document = json.loads(json.dumps(document))
    restored = ProvenanceConstraintSet.from_document(json_document)

    assert json_document["codec"] == {
        "name": CODEC_NAME,
        "version": CODEC_VERSION,
    }
    assert restored.to_document() == document
    assert (
        document["transformation_runs"][2]["consumed"][0]["quantity"]
        == {"amount": "1.2300", "unit": "liter"}
    )
    assert (
        document["transformation_runs"][2]["losses"][0]["quantity"]
        == {"amount": "0.0300", "unit": "liter"}
    )
    assert (
        document["assembly_runs"][0]["components"][1]["role"]
        == "power lead"
    )
    assert "minimum" not in json.dumps(document)
    assert "maximum" not in json.dumps(document)

    with pytest.raises(FrozenInstanceError):
        restored.transformations = ()


def test_rehydrated_network_preserves_loss_assembly_and_solver_behavior():
    document = worked_constraint_set().to_document()
    network = provenance_network_from_document(document)

    loss = network.contribution_bounds("BAT-RAW", ["LOSS-EVAPORATION"])
    assert loss.minimum == Decimal("0.0300")
    assert loss.maximum == Decimal("0.0300")
    assert loss.unit == "liter"

    component = network.direct_component_bounds(
        "BAT-WIRE",
        "BAT-CONTROLLER",
    )
    assert component.minimum == Decimal("20.00")
    assert component.maximum == Decimal("20.00")
    assert component.unit == "centimeter"

    with pytest.raises(GeneralSolverRequired, match="mixed allocation semantics"):
        network.contribution_bounds("BAT-A", ["BAT-D1"])


@pytest.mark.parametrize("version", [2, 0, True, "1"])
def test_unknown_or_mistyped_codec_versions_fail_closed(version):
    document = worked_constraint_set().to_document()
    document["codec"]["version"] = version

    with pytest.raises(ValueError, match="unsupported provenance codec version"):
        ProvenanceConstraintSet.from_document(document)


def test_unknown_codec_and_document_fields_fail_closed():
    document = worked_constraint_set().to_document()
    document["codec"]["name"] = "inventorius.future-provenance"
    with pytest.raises(ValueError, match="unsupported provenance codec"):
        ProvenanceConstraintSet.from_document(document)

    document = worked_constraint_set().to_document()
    document["derived_bounds"] = []
    with pytest.raises(ValueError, match="unexpected.*derived_bounds"):
        ProvenanceConstraintSet.from_document(document)


def test_decimal_amounts_must_be_exact_positive_finite_strings():
    for invalid in [1, "Infinity", "-Infinity", "NaN", "0", "-1"]:
        document = worked_constraint_set().to_document()
        document["transformation_runs"][0]["consumed"][0]["quantity"][
            "amount"
        ] = invalid
        with pytest.raises(ValueError, match="decimal string|finite and positive"):
            ProvenanceConstraintSet.from_document(document)

    infinite = TransformationRun(
        run_id="RUN-infinite",
        consumed=(consumed("BAT-A", "Infinity"),),
        produced=(produced("BAT-B", "Infinity"),),
    )
    with pytest.raises(ValueError, match="finite and positive"):
        ProvenanceConstraintSet((infinite,))


def test_nonblank_identities_and_roles_are_required():
    blank_holding = TransformationRun(
        run_id="RUN-blank-input",
        consumed=(consumed(" ", "1"),),
        produced=(produced("BAT-B", "1"),),
    )
    with pytest.raises(ValueError, match="batch_id must be a nonblank string"):
        ProvenanceConstraintSet((blank_holding,))

    blank_role = AssemblyRun(
        run_id="RUN-blank-role",
        components=(
            ComponentUse(
                HoldingReference("BAT-A", "BIN-A"),
                Quantity(1, "item"),
                " ",
            ),
        ),
        produced=produced("BAT-ASSEMBLY", "1", "item"),
    )
    with pytest.raises(ValueError, match="role must be a nonblank string"):
        ProvenanceConstraintSet(assemblies=(blank_role,))


def test_run_ids_are_unique_across_run_types():
    transformation = TransformationRun(
        run_id="RUN-SHARED",
        consumed=(consumed("BAT-A", "1"),),
        produced=(produced("BAT-B", "1"),),
    )
    assembly = AssemblyRun(
        run_id="RUN-SHARED",
        components=(
            ComponentUse(
                HoldingReference("BAT-C", "BIN-C"),
                Quantity(1, "item"),
                "part",
            ),
        ),
        produced=produced("BAT-D", "1", "item"),
    )

    with pytest.raises(ValueError, match="duplicate run: RUN-SHARED"):
        ProvenanceConstraintSet((transformation,), (assembly,))


def test_output_ids_are_unique_across_producer_types():
    transformation = TransformationRun(
        run_id="RUN-transform",
        consumed=(consumed("BAT-A", "1"),),
        produced=(produced("BAT-SHARED", "1"),),
    )
    assembly = AssemblyRun(
        run_id="RUN-assemble",
        components=(
            ComponentUse(
                HoldingReference("BAT-C", "BIN-C"),
                Quantity(1, "item"),
                "part",
            ),
        ),
        produced=produced("BAT-SHARED", "1", "item"),
    )

    with pytest.raises(
        ValueError,
        match="output already has a producer: BAT-SHARED",
    ):
        ProvenanceConstraintSet((transformation,), (assembly,))


def test_unknown_allocation_semantics_fail_closed():
    document = worked_constraint_set().to_document()
    document["transformation_runs"][0]["allocation"] = "magic-apportionment"

    with pytest.raises(ValueError, match="unsupported semantics"):
        ProvenanceConstraintSet.from_document(document)
