"""Persistence-level proofs for transactional inventory writes."""

from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest

from inventorius.db import get_mongo_client
from inventorius.inventory_repository import InventoryRepository, canonical_fingerprint
from inventorius.ledger import (
    HoldingKey,
    HoldingLeg,
    InsufficientHolding,
    InventoryOperation,
    OperationKind,
)


@pytest.fixture
def inventory_database():
    database = get_mongo_client().testing
    collections = (
        database.batch,
        database.bin,
        database.inventory_code_observations,
        database.inventory_counters,
        database.inventory_holdings,
        database.inventory_operations,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    yield database
    for collection in collections:
        collection.delete_many({})


def receive_operation(key="repository-receive"):
    return InventoryOperation(
        operation_id="OP-repository-receive",
        idempotency_key=key,
        kind=OperationKind.RECEIVE,
        legs=(HoldingLeg(HoldingKey("BAT000001", "BIN000001", "each"), 4),),
    )


def test_post_is_idempotent_and_persists_decimal128_projection(inventory_database):
    repository = InventoryRepository(inventory_database)
    operation = receive_operation()
    fingerprint = canonical_fingerprint({"kind": "receive", "quantity": 4})

    first = repository.post(
        operation,
        request_fingerprint=fingerprint,
        result={"operation_id": operation.operation_id},
    )
    replay = repository.post(
        operation,
        request_fingerprint=fingerprint,
        result={"operation_id": operation.operation_id},
    )

    assert not first.replayed
    assert replay.replayed
    assert inventory_database.inventory_operations.count_documents({}) == 1
    holding = inventory_database.inventory_holdings.find_one({})
    assert holding["quantity"].to_decimal() == Decimal(4)
    operation_document = inventory_database.inventory_operations.find_one({})
    assert operation_document["legs"][0]["quantity"].to_decimal() == Decimal(4)


def test_capture_rolls_back_every_document_when_the_transaction_fails(
    inventory_database, monkeypatch
):
    inventory_database.bin.insert_one({
        "_id": "BIN000001", "contents": {}, "props": {},
    })
    repository = InventoryRepository(inventory_database)

    def fail_after_identity(*args, **kwargs):
        raise RuntimeError("simulate write failure after identity creation")

    monkeypatch.setattr(repository, "_apply_projection", fail_after_identity)
    with pytest.raises(RuntimeError, match="simulate write failure"):
        repository.capture_intake(
            {
                "description": "failed capture",
                "bin_id": "BIN000001",
                "quantity": 1,
                "unit": "each",
                "observed_codes": ["failed-code"],
            },
            idempotency_key="rollback-capture",
        )

    assert inventory_database.sku.count_documents({}) == 0
    assert inventory_database.batch.count_documents({}) == 0
    assert inventory_database.inventory_code_observations.count_documents({}) == 0
    assert inventory_database.inventory_counters.count_documents({}) == 0
    assert inventory_database.inventory_operations.count_documents({}) == 0
    assert inventory_database.inventory_holdings.count_documents({}) == 0


def test_concurrent_releases_cannot_double_debit_a_holding(inventory_database):
    repository = InventoryRepository(inventory_database)
    source = HoldingKey("BAT000001", "BIN000001", "each")
    repository.post(
        InventoryOperation(
            operation_id="OP-seed",
            idempotency_key="seed",
            kind=OperationKind.RECEIVE,
            legs=(HoldingLeg(source, 5),),
        ),
        request_fingerprint=canonical_fingerprint({"seed": 5}),
        result={"operation_id": "OP-seed"},
    )

    barrier = Barrier(2)
    lock = Lock()
    entered = 0
    apply_projection = repository._apply_projection

    def synchronize_first_two(operation, session, now):
        nonlocal entered
        if operation.kind == OperationKind.RELEASE:
            with lock:
                entered += 1
                synchronize = entered <= 2
            if synchronize:
                barrier.wait(timeout=10)
        return apply_projection(operation, session, now)

    repository._apply_projection = synchronize_first_two

    def release(number):
        operation = InventoryOperation(
            operation_id=f"OP-release-{number}",
            idempotency_key=f"release-{number}",
            kind=OperationKind.RELEASE,
            legs=(HoldingLeg(source, -4),),
        )
        try:
            repository.post(
                operation,
                request_fingerprint=canonical_fingerprint({"release": number}),
                result={"operation_id": operation.operation_id},
            )
            return "committed"
        except InsufficientHolding:
            return "insufficient"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(release, (1, 2)))

    assert sorted(outcomes) == ["committed", "insufficient"]
    holding = inventory_database.inventory_holdings.find_one({})
    assert holding["quantity"].to_decimal() == Decimal(1)
    assert inventory_database.inventory_operations.count_documents({}) == 2


def test_concurrent_same_key_on_different_holdings_replays_the_winner(
    inventory_database
):
    repository = InventoryRepository(inventory_database)
    barrier = Barrier(2)
    lock = Lock()
    entered = 0
    apply_projection = repository._apply_projection

    def synchronize_first_two(operation, session, now):
        nonlocal entered
        with lock:
            entered += 1
            synchronize = entered <= 2
        if synchronize:
            barrier.wait(timeout=10)
        return apply_projection(operation, session, now)

    repository._apply_projection = synchronize_first_two
    fingerprint = canonical_fingerprint({"same": "command"})

    def post_to(location_id):
        operation = InventoryOperation(
            operation_id=f"OP-{location_id}",
            idempotency_key="same-key",
            kind=OperationKind.RECEIVE,
            legs=(HoldingLeg(HoldingKey("BAT000001", location_id, "each"), 1),),
        )
        return repository.post(
            operation,
            request_fingerprint=fingerprint,
            result={"operation_id": operation.operation_id},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(post_to, ("BIN000001", "BIN000002")))

    assert sorted(result.replayed for result in results) == [False, True]
    assert inventory_database.inventory_operations.count_documents({}) == 1
    assert inventory_database.inventory_holdings.count_documents({}) == 1
