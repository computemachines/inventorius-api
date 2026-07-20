"""Scenarios for the append-only operation ledger."""

from decimal import Decimal

import pytest

from inventorius.ledger import (
    HoldingKey,
    HoldingLeg,
    IdempotencyConflict,
    InsufficientHolding,
    InventoryLedger,
    InventoryOperation,
    OperationKind,
)


BIN_A = HoldingKey("BAT000001", "BIN000001", "item")
BIN_B = HoldingKey("BAT000001", "BIN000002", "item")


def operation(
    operation_id: str,
    kind: OperationKind,
    legs: tuple[HoldingLeg, ...],
    *,
    idempotency_key: str | None = None,
    corrects_operation_id: str | None = None,
):
    return InventoryOperation(
        operation_id=operation_id,
        idempotency_key=idempotency_key or f"request-{operation_id}",
        kind=kind,
        legs=legs,
        corrects_operation_id=corrects_operation_id,
    )


def test_receive_transfer_and_release_rebuild_current_holdings():
    operations = (
        operation(
            "OP-receive",
            OperationKind.RECEIVE,
            (HoldingLeg(BIN_A, 10),),
        ),
        operation(
            "OP-transfer",
            OperationKind.TRANSFER,
            (HoldingLeg(BIN_A, -3), HoldingLeg(BIN_B, 3)),
        ),
        operation(
            "OP-release",
            OperationKind.RELEASE,
            (HoldingLeg(BIN_B, -2),),
        ),
    )

    ledger = InventoryLedger()
    for event in operations:
        ledger.post(event)
    assert ledger.balance(BIN_A) == Decimal(7)
    assert ledger.balance(BIN_B) == Decimal(1)

    rebuilt = InventoryLedger()
    rebuilt.rebuild(operations)
    assert rebuilt.balance(BIN_A) == Decimal(7)
    assert rebuilt.balance(BIN_B) == Decimal(1)


def test_rejected_operation_does_not_partially_change_balances():
    ledger = InventoryLedger()
    ledger.post(operation(
        "OP-receive",
        OperationKind.RECEIVE,
        (HoldingLeg(BIN_A, 2),),
    ))

    with pytest.raises(InsufficientHolding):
        ledger.post(operation(
            "OP-too-large",
            OperationKind.TRANSFER,
            (HoldingLeg(BIN_A, -3), HoldingLeg(BIN_B, 3)),
        ))

    assert ledger.balance(BIN_A) == Decimal(2)
    assert ledger.balance(BIN_B) == Decimal(0)


def test_transfer_rejects_a_debit_and_credit_to_the_same_holding():
    with pytest.raises(ValueError, match="distinct holdings"):
        operation(
            "OP-no-op",
            OperationKind.TRANSFER,
            (HoldingLeg(BIN_A, -1), HoldingLeg(BIN_A, 1)),
        )


def test_retry_is_idempotent_but_reusing_key_for_new_command_is_not():
    ledger = InventoryLedger()
    receive = operation(
        "OP-receive",
        OperationKind.RECEIVE,
        (HoldingLeg(BIN_A, 5),),
        idempotency_key="scanner-command-1",
    )

    assert ledger.post(receive) is receive
    assert ledger.post(receive) is receive
    assert ledger.balance(BIN_A) == Decimal(5)

    conflicting = operation(
        "OP-other",
        OperationKind.RECEIVE,
        (HoldingLeg(BIN_A, 7),),
        idempotency_key="scanner-command-1",
    )
    with pytest.raises(IdempotencyConflict):
        ledger.post(conflicting)


def test_only_validated_operation_kinds_are_exposed_at_this_stage():
    assert {kind.value for kind in OperationKind} == {
        "receive", "release", "transfer", "repackage", "transformation",
        "assembly", "correction",
    }

    with pytest.raises(ValueError, match="unsupported inventory operation kind"):
        InventoryOperation(
            operation_id="OP-correction",
            idempotency_key="correction-1",
            kind=OperationKind.CORRECTION,
            legs=(HoldingLeg(BIN_A, -1),),
            corrects_operation_id="OP-original",
        )


def test_packaging_states_are_distinct_holdings_with_supported_receives():
    sealed = HoldingKey("BAT000001", "BIN000001", "case", "PACK-10x12")
    loose = HoldingKey("BAT000001", "BIN000001", "each", "PACK-10x12")
    ledger = InventoryLedger()
    ledger.post(operation(
        "OP-receive-case", OperationKind.RECEIVE, (HoldingLeg(sealed, 1),),
    ))
    ledger.post(operation(
        "OP-receive-loose", OperationKind.RECEIVE, (HoldingLeg(loose, 120),),
    ))

    assert ledger.balance(sealed) == Decimal(1)
    assert ledger.balance(loose) == Decimal(120)
