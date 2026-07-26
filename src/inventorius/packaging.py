"""Packaging-state arithmetic which preserves batch identity and lineage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from inventorius.provenance import Quantity


@dataclass(frozen=True)
class PackageLevel:
    """One named package containing an exact amount of a smaller unit."""

    unit: str
    contains: Quantity

    def __post_init__(self):
        if not self.unit:
            raise ValueError("package unit must not be empty")
        if self.unit == self.contains.unit:
            raise ValueError("a package level cannot contain itself")


@dataclass(frozen=True)
class RepackagingRun:
    """A packaging-state change with no batch or lineage change."""

    run_id: str
    configuration_id: str
    batch_id: str
    location_id: str
    opened: Quantity
    resulting: tuple[Quantity, ...]


class PackagingConfiguration:
    """An exact conversion graph for one concrete packaging configuration."""

    def __init__(
        self,
        configuration_id: str,
        sku_id: str,
        base_unit: str,
        levels: tuple[PackageLevel, ...],
    ):
        if not configuration_id or not sku_id or not base_unit:
            raise ValueError("packaging identity and base unit must not be empty")

        self.configuration_id = configuration_id
        self.sku_id = sku_id
        self.base_unit = base_unit
        self._levels: dict[str, PackageLevel] = {}
        for level in levels:
            if level.unit == base_unit:
                raise ValueError("the base unit is not a package level")
            if level.unit in self._levels:
                raise ValueError(f"duplicate package unit: {level.unit}")
            self._levels[level.unit] = level

        for unit in self._levels:
            self._factor_to_base(unit, visiting=set())

    def base_amount(self, quantity: Quantity) -> Decimal:
        """Normalize a packaged amount to the configuration's base unit."""

        return quantity.amount * self._factor_to_base(
            quantity.unit,
            visiting=set(),
        )

    def validate_repackaging(self, run: RepackagingRun) -> None:
        if run.configuration_id != self.configuration_id:
            raise ValueError("repackaging uses a different configuration")
        if not run.batch_id or not run.location_id:
            raise ValueError("repackaging must retain batch and location")
        if not run.resulting:
            raise ValueError("repackaging must produce a packaging state")

        opened = self.base_amount(run.opened)
        resulting = sum(
            (self.base_amount(quantity) for quantity in run.resulting),
            Decimal(0),
        )
        if opened != resulting:
            raise ValueError("repackaging must preserve base quantity")

    def _factor_to_base(self, unit: str, visiting: set[str]) -> Decimal:
        if unit == self.base_unit:
            return Decimal(1)
        level = self._levels.get(unit)
        if level is None:
            raise ValueError(f"unknown packaging unit: {unit}")
        if unit in visiting:
            raise ValueError("packaging levels contain a cycle")

        visiting.add(unit)
        factor = level.contains.amount * self._factor_to_base(
            level.contains.unit,
            visiting,
        )
        visiting.remove(unit)
        return factor
