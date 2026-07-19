"""Scenarios for cases, nested packages, and unpacking."""

import pytest

from inventorius.packaging import (
    PackageLevel,
    PackagingConfiguration,
    RepackagingRun,
)
from inventorius.provenance import Quantity


@pytest.fixture
def glue_stick_packaging():
    return PackagingConfiguration(
        configuration_id="PACK-GLUE-10x12",
        sku_id="SKU-GLUE-STICK",
        base_unit="item",
        levels=(
            PackageLevel("box", Quantity(12, "item")),
            PackageLevel("case", Quantity(10, "box")),
        ),
    )


def test_nested_package_quantities_normalize_without_ambiguity(
    glue_stick_packaging,
):
    assert glue_stick_packaging.base_amount(Quantity(1, "case")) == 120
    assert glue_stick_packaging.base_amount(Quantity(3, "box")) == 36
    assert glue_stick_packaging.base_amount(Quantity(7, "item")) == 7


def test_opening_a_case_changes_packaging_not_batch_identity(
    glue_stick_packaging,
):
    run = RepackagingRun(
        run_id="RUN-open-case",
        configuration_id="PACK-GLUE-10x12",
        batch_id="BAT-GLUE-2026-07",
        location_id="BIN000145",
        opened=Quantity(1, "case"),
        resulting=(Quantity(9, "box"), Quantity(12, "item")),
    )

    glue_stick_packaging.validate_repackaging(run)
    assert run.batch_id == "BAT-GLUE-2026-07"


def test_repackaging_rejects_quantity_creation(glue_stick_packaging):
    run = RepackagingRun(
        run_id="RUN-impossible-unpack",
        configuration_id="PACK-GLUE-10x12",
        batch_id="BAT-GLUE-2026-07",
        location_id="BIN000145",
        opened=Quantity(1, "case"),
        resulting=(Quantity(121, "item"),),
    )

    with pytest.raises(ValueError, match="preserve base quantity"):
        glue_stick_packaging.validate_repackaging(run)


def test_package_configuration_rejects_cycles_and_unknown_units():
    with pytest.raises(ValueError, match="cycle"):
        PackagingConfiguration(
            configuration_id="PACK-cycle",
            sku_id="SKU-example",
            base_unit="item",
            levels=(
                PackageLevel("box", Quantity(2, "case")),
                PackageLevel("case", Quantity(3, "box")),
            ),
        )

    packaging = PackagingConfiguration(
        configuration_id="PACK-simple",
        sku_id="SKU-example",
        base_unit="item",
        levels=(),
    )
    with pytest.raises(ValueError, match="unknown packaging unit"):
        packaging.base_amount(Quantity(1, "case"))
