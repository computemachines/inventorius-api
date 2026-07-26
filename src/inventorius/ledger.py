"""Append-only inventory operations and a rebuildable holding projection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable


def _decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class OperationKind(str, Enum):
    RECEIVE = "receive"
    TRANSFER = "transfer"
    RELEASE = "release"
    REPACKAGE = "repackage"
    TRANSFORMATION = "transformation"
    ASSEMBLY = "assembly"
    CORRECTION = "correction"
    RECONCILIATION = "reconciliation"


SUPPORTED_OPERATION_KINDS = {
    OperationKind.RECEIVE,
    OperationKind.TRANSFER,
    OperationKind.RELEASE,
}

INTERNAL_OPERATION_KINDS = SUPPORTED_OPERATION_KINDS | {
    OperationKind.CORRECTION,
    OperationKind.RECONCILIATION,
}


@dataclass(frozen=True)
class HoldingKey:
    batch_id: str
    location_id: str
    unit: str
    packaging_configuration_id: str | None = None

    def __post_init__(self):
        if not self.batch_id or not self.location_id or not self.unit:
            raise ValueError("holding identity must not be empty")


@dataclass(frozen=True)
class HoldingLeg:
    holding: HoldingKey
    amount: Decimal

    def __init__(
        self,
        holding: HoldingKey,
        amount: Decimal | int | str,
    ):
        amount = _decimal(amount)
        if amount == 0:
            raise ValueError("holding leg must change a balance")
        object.__setattr__(self, "holding", holding)
        object.__setattr__(self, "amount", amount)


@dataclass(frozen=True)
class InventoryOperation:
    operation_id: str
    idempotency_key: str
    kind: OperationKind
    legs: tuple[HoldingLeg, ...]
    corrects_operation_id: str | None = None
    reconciles_observation_id: str | None = None

    def __post_init__(self):
        if not self.operation_id or not self.idempotency_key:
            raise ValueError("operation identity must not be empty")
        if not self.legs:
            raise ValueError("an operation needs holding legs")
        if self.kind not in INTERNAL_OPERATION_KINDS:
            raise ValueError(
                f"unsupported inventory operation kind: {self.kind.value}"
            )

        if self.kind == OperationKind.CORRECTION:
            if not self.corrects_operation_id:
                raise ValueError("correction must reference an earlier operation")
            if self.corrects_operation_id == self.operation_id:
                raise ValueError("correction cannot reference itself")
            if self.reconciles_observation_id is not None:
                raise ValueError("correction cannot reconcile an audit observation")
            return
        if self.kind == OperationKind.RECONCILIATION:
            if not self.reconciles_observation_id:
                raise ValueError(
                    "reconciliation must reference an audit observation"
                )
            if self.corrects_operation_id is not None:
                raise ValueError("reconciliation cannot correct an operation")
            return
        if (
            self.corrects_operation_id is not None
            or self.reconciles_observation_id is not None
        ):
            raise ValueError(
                "ordinary operations cannot reference corrections or observations"
            )

        if self.kind == OperationKind.RECEIVE:
            if any(leg.amount < 0 for leg in self.legs):
                raise ValueError("receiving may only credit holdings")
        elif self.kind == OperationKind.RELEASE:
            if any(leg.amount > 0 for leg in self.legs):
                raise ValueError("releasing may only debit holdings")
        elif self.kind == OperationKind.TRANSFER:
            self._validate_transfer()

    def _validate_transfer(self) -> None:
        if len({leg.holding for leg in self.legs}) < 2:
            raise ValueError("transfer needs distinct holdings")
        totals: dict[tuple[str, str, str | None], Decimal] = defaultdict(Decimal)
        for leg in self.legs:
            key = (
                leg.holding.batch_id,
                leg.holding.unit,
                leg.holding.packaging_configuration_id,
            )
            totals[key] += leg.amount
        if any(total != 0 for total in totals.values()):
            raise ValueError("transfer must preserve each batch and package unit")
        if not any(leg.amount < 0 for leg in self.legs):
            raise ValueError("transfer needs a source holding")
        if not any(leg.amount > 0 for leg in self.legs):
            raise ValueError("transfer needs a destination holding")


class InsufficientHolding(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


class InventoryLedger:
    """In-memory reference projection for operation and repository tests."""

    def __init__(self):
        self._operations: dict[str, InventoryOperation] = {}
        self._operation_id_by_key: dict[str, str] = {}
        self._correction_id_by_original: dict[str, str] = {}
        self._reconciliation_id_by_observation: dict[str, str] = {}
        self._balances: dict[HoldingKey, Decimal] = {}

    def post(self, operation: InventoryOperation) -> InventoryOperation:
        existing_id = self._operation_id_by_key.get(operation.idempotency_key)
        if existing_id is not None:
            existing = self._operations[existing_id]
            if existing == operation:
                return existing
            raise IdempotencyConflict(
                "idempotency key already belongs to another operation"
            )
        if operation.operation_id in self._operations:
            raise ValueError(f"duplicate operation: {operation.operation_id}")
        if operation.kind == OperationKind.CORRECTION:
            original_id = operation.corrects_operation_id
            original = self._operations.get(original_id)
            if original is None:
                raise ValueError(
                    "correction must reference an earlier stored operation"
                )
            if original.kind == OperationKind.CORRECTION:
                raise ValueError("a correction cannot correct another correction")
            if original_id in self._correction_id_by_original:
                raise ValueError("operation already has a correction")
        if operation.kind == OperationKind.RECONCILIATION:
            observation_id = operation.reconciles_observation_id
            if observation_id in self._reconciliation_id_by_observation:
                raise ValueError(
                    "audit observation already has a reconciliation"
                )
        deltas: dict[HoldingKey, Decimal] = defaultdict(Decimal)
        for leg in operation.legs:
            deltas[leg.holding] += leg.amount

        resulting = {
            holding: self._balances.get(holding, Decimal(0)) + delta
            for holding, delta in deltas.items()
        }
        negative = [
            holding
            for holding, amount in resulting.items()
            if amount < 0
        ]
        if negative:
            raise InsufficientHolding(
                f"operation would make a holding negative: {negative[0]}"
            )

        for holding, amount in resulting.items():
            if amount == 0:
                self._balances.pop(holding, None)
            else:
                self._balances[holding] = amount
        self._operations[operation.operation_id] = operation
        self._operation_id_by_key[operation.idempotency_key] = (
            operation.operation_id
        )
        if operation.kind == OperationKind.CORRECTION:
            self._correction_id_by_original[operation.corrects_operation_id] = (
                operation.operation_id
            )
        if operation.kind == OperationKind.RECONCILIATION:
            self._reconciliation_id_by_observation[
                operation.reconciles_observation_id
            ] = operation.operation_id
        return operation

    def balance(self, holding: HoldingKey) -> Decimal:
        return self._balances.get(holding, Decimal(0))

    def rebuild(self, operations: Iterable[InventoryOperation]) -> None:
        self._operations.clear()
        self._operation_id_by_key.clear()
        self._correction_id_by_original.clear()
        self._reconciliation_id_by_observation.clear()
        self._balances.clear()
        for operation in operations:
            self.post(operation)
