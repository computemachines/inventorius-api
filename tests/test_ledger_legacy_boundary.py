"""Regression tests for the boundary between legacy contents and the ledger."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest

from inventorius.inventory_repository import (
    InventoryRepository,
    LedgerReferencedBin,
    MissingBin,
    canonical_fingerprint,
)
from inventorius.ledger import HoldingKey, HoldingLeg, InventoryOperation, OperationKind
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_inventory_database():
    database = get_test_database()
    for collection in (
        database.admin,
        database.batch,
        database.bin,
        database.inventory_code_observations,
        database.inventory_counters,
        database.inventory_holdings,
        database.inventory_operations,
        database.sku,
    ):
        collection.delete_many({})
    yield database
    for collection in (
        database.admin,
        database.batch,
        database.bin,
        database.inventory_code_observations,
        database.inventory_counters,
        database.inventory_holdings,
        database.inventory_operations,
        database.sku,
    ):
        collection.delete_many({})


def _seed_released_ledger_batch(database):
    database.bin.insert_many([
        {"_id": "BIN000001", "contents": {}, "props": {}},
        {"_id": "BIN000002", "contents": {}, "props": {}},
    ])
    database.sku.insert_one({
        "_id": "SKU000001", "name": "ledger item", "owned_codes": [],
        "associated_codes": [], "props": {},
    })
    database.batch.insert_one({
        "_id": "BAT000001", "sku_id": "SKU000001", "name": "ledger item",
        "owned_codes": [], "associated_codes": [], "props": {},
    })
    repository = InventoryRepository(database)
    holding = HoldingKey("BAT000001", "BIN000001", "each")
    for operation_id, key, amount in (
        ("OP-seed-receive", "seed-receive", 1),
        ("OP-seed-release", "seed-release", -1),
    ):
        operation = InventoryOperation(
            operation_id=operation_id,
            idempotency_key=key,
            kind=OperationKind.RECEIVE if amount > 0 else OperationKind.RELEASE,
            legs=(HoldingLeg(holding, amount),),
        )
        repository.post(
            operation,
            request_fingerprint=canonical_fingerprint({"operation": operation_id}),
            result={"operation_id": operation_id},
        )
    return holding


def test_legacy_contents_endpoints_are_retired_at_zero_balance(
    client, clean_inventory_database
):
    holding = _seed_released_ledger_batch(clean_inventory_database)
    projected = clean_inventory_database.inventory_holdings.find_one({
        "batch_id": holding.batch_id,
    })
    assert projected["quantity"].to_decimal() == Decimal(0)

    for item_id in ("SKU000001", "BAT000001"):
        receive_or_release = [
            client.post(
                "/api/bin/BIN000001/contents",
                json={"id": item_id, "quantity": quantity},
            )
            for quantity in (1, -1)
        ]
        move = client.put(
            "/api/bin/BIN000001/contents/move",
            json={"id": item_id, "quantity": 1, "destination": "BIN000002"},
        )
        for response in (*receive_or_release, move):
            assert response.status_code == 410
            assert response.json == {
                "type": "operation-retired",
                "title": "This inventory mutation endpoint has been retired.",
                "replacement": "/api/inventory-operations",
            }

    # Neither rejected legacy request has written a second accounting record.
    assert clean_inventory_database.bin.find_one({"_id": "BIN000001"})["contents"] == {}
    assert clean_inventory_database.bin.find_one({"_id": "BIN000002"})["contents"] == {}


def test_ledger_referenced_bin_cannot_be_force_deleted_at_zero_balance(
    client, clean_inventory_database
):
    _seed_released_ledger_batch(clean_inventory_database)

    for suffix in ("", "?force=true"):
        response = client.delete(f"/api/bin/BIN000001{suffix}")
        assert response.status_code == 409
        assert response.json["type"] == "ledger-history-conflict"
    assert clean_inventory_database.bin.find_one({"_id": "BIN000001"}) is not None


def test_force_delete_remains_available_for_a_genuinely_legacy_bin(
    client, clean_inventory_database
):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000099", "contents": {"SKU000099": 2}, "props": {},
    })

    response = client.delete("/api/bin/BIN000099?force=true")
    assert response.status_code == 200
    assert clean_inventory_database.bin.find_one({"_id": "BIN000099"}) is None


def test_concurrent_capture_and_delete_leave_no_orphaned_operation(
    clean_inventory_database,
):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000001", "contents": {}, "props": {},
    })
    capture_repository = InventoryRepository(clean_inventory_database)
    delete_repository = InventoryRepository(clean_inventory_database)
    start = Barrier(2)

    def capture():
        start.wait(timeout=10)
        try:
            capture_repository.capture_intake(
                {
                    "description": "concurrent capture",
                    "bin_id": "BIN000001",
                    "quantity": 1,
                    "unit": "each",
                    "observed_codes": [],
                },
                idempotency_key="concurrent-capture",
            )
            return "captured"
        except MissingBin:
            return "missing-bin"

    def delete():
        start.wait(timeout=10)
        try:
            return "deleted" if delete_repository.delete_legacy_bin(
                "BIN000001", force=False
            ) else "force-required"
        except LedgerReferencedBin:
            return "ledger-protected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = set(executor.map(lambda action: action(), (capture, delete)))

    assert outcomes in ({"captured", "ledger-protected"}, {"missing-bin", "deleted"})
    operation = clean_inventory_database.inventory_operations.find_one({})
    bin_document = clean_inventory_database.bin.find_one({"_id": "BIN000001"})
    if operation is None:
        assert bin_document is None
        assert clean_inventory_database.inventory_holdings.count_documents({}) == 0
    else:
        assert bin_document is not None
        assert operation["legs"][0]["location_id"] == "BIN000001"
