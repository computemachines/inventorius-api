"""HTTP-level proofs for the canonical ledger inventory commands."""

from decimal import Decimal

import pytest

from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_inventory_database():
    database = get_test_database()
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
    for bin_id in ("BIN000001", "BIN000002"):
        database.bin.insert_one({"_id": bin_id, "contents": {}, "props": {}})
    database.batch.insert_one({
        "_id": "BAT000001",
        "name": "Test batch",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    yield database
    for collection in collections:
        collection.delete_many({})


def post_command(client, key, **command):
    return client.post(
        "/api/inventory-operations",
        headers={"Idempotency-Key": key},
        json=command,
    )


def test_receive_transfer_release_are_immutable_operations_with_holdings(
    client, clean_inventory_database
):
    receive = post_command(
        client,
        "receive-test-batch",
        kind="receive",
        batch_id="BAT1",
        location_id="BIN1",
        quantity=5,
    )
    assert receive.status_code == 201
    assert receive.json["state"] == {
        "operation_id": receive.json["state"]["operation_id"],
        "kind": "receive",
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "quantity": 5,
        "unit": "each",
        "packaging_configuration_id": None,
    }

    transfer = post_command(
        client,
        "transfer-test-batch",
        kind="transfer",
        batch_id="BAT000001",
        source_location_id="BIN000001",
        destination_location_id="BIN000002",
        quantity=2,
        unit="each",
    )
    assert transfer.status_code == 201
    assert transfer.json["state"] == {
        "operation_id": transfer.json["state"]["operation_id"],
        "kind": "transfer",
        "batch_id": "BAT000001",
        "source_location_id": "BIN000001",
        "destination_location_id": "BIN000002",
        "quantity": 2,
        "unit": "each",
        "packaging_configuration_id": None,
    }

    release = post_command(
        client,
        "release-test-batch",
        kind="release",
        batch_id="BAT000001",
        location_id="BIN000002",
        quantity=1,
    )
    assert release.status_code == 201

    holdings = {
        holding["location_id"]: holding["quantity"].to_decimal()
        for holding in clean_inventory_database.inventory_holdings.find({})
    }
    assert holdings == {"BIN000001": Decimal(3), "BIN000002": Decimal(1)}
    assert clean_inventory_database.inventory_operations.count_documents({}) == 3

    operation_kinds = [
        operation["kind"]
        for operation in clean_inventory_database.inventory_operations.find({})
    ]
    assert set(operation_kinds) == {"receive", "transfer", "release"}
    transfer_document = clean_inventory_database.inventory_operations.find_one({
        "_id": transfer.json["state"]["operation_id"],
    })
    assert {
        (leg["location_id"], leg["quantity"].to_decimal())
        for leg in transfer_document["legs"]
    } == {("BIN000001", Decimal(-2)), ("BIN000002", Decimal(2))}

    # Clean-break commands never mutate the legacy projection.
    assert clean_inventory_database.bin.find_one({"_id": "BIN000001"})["contents"] == {}
    assert clean_inventory_database.bin.find_one({"_id": "BIN000002"})["contents"] == {}


def test_command_replays_exactly_and_rejects_a_reused_key(
    client, clean_inventory_database
):
    command = {
        "kind": "receive",
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "quantity": 3,
    }
    first = post_command(client, "scan-retry", **command)
    replay = post_command(client, "scan-retry", **command)
    conflict = post_command(client, "scan-retry", **{**command, "quantity": 4})

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert conflict.status_code == 409
    assert clean_inventory_database.inventory_operations.count_documents({}) == 1
    holding = clean_inventory_database.inventory_holdings.find_one({})
    assert holding["quantity"].to_decimal() == Decimal(3)


@pytest.mark.parametrize("command, parameter", [
    ({"kind": "receive", "batch_id": "BAT1", "quantity": 1}, "location_id"),
    ({"kind": "release", "batch_id": "BAT1", "quantity": 1}, "location_id"),
    ({
        "kind": "receive", "batch_id": "SKU1", "quantity": 1,
        "location_id": "BIN1",
    }, "batch_id"),
    ({
        "kind": "receive", "batch_id": "BAT1", "quantity": 0,
        "location_id": "BIN1",
    }, "quantity"),
    ({
        "kind": "receive", "batch_id": "BAT1", "quantity": 1,
        "unit": "gram", "location_id": "BIN1",
    }, "unit"),
    ({
        "kind": "receive", "batch_id": "BAT1", "quantity": 1,
        "location_id": "BIN1", "source_location_id": "BIN2",
    }, "source_location_id"),
    ({
        "kind": "transfer", "batch_id": "BAT1", "quantity": 1,
        "source_location_id": "BIN1", "destination_location_id": "BIN1",
    }, "destination_location_id"),
    ({
        "kind": "receive", "batch_id": "BAT1", "quantity": 1,
        "location_id": "BIN1", "packaging_configuration_id": "PKG1",
    }, "packaging_configuration_id"),
])
def test_command_rejects_invalid_domain_shape(
    client, clean_inventory_database, command, parameter
):
    response = post_command(client, f"invalid-{parameter}", **command)

    assert response.status_code == 400
    assert response.json["type"] == "validation-error"
    assert response.json["invalid-params"][0]["name"] == parameter
    assert clean_inventory_database.inventory_operations.count_documents({}) == 0


def test_command_requires_an_idempotency_key(client, clean_inventory_database):
    response = client.post("/api/inventory-operations", json={
        "kind": "receive",
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "quantity": 1,
    })

    assert response.status_code == 400
    assert response.json["type"] == "validation-error"
    assert response.json["invalid-params"] == [{
        "name": "Idempotency-Key",
        "reason": "header is required",
    }]
    assert clean_inventory_database.inventory_operations.count_documents({}) == 0


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/api/bin/not-a-bin/contents"),
        ("put", "/api/bin/not-a-bin/contents/move"),
    ],
)
def test_retired_inventory_routes_are_unconditionally_gone(client, method, path):
    response = getattr(client, method)(path, json={})

    assert response.status_code == 410
    assert response.json["type"] == "operation-retired"
    assert response.json["replacement"] == "/api/inventory-operations"


def test_command_checks_resources_and_insufficient_holding_without_partial_write(
    client, clean_inventory_database
):
    missing_batch = post_command(
        client,
        "missing-batch",
        kind="receive",
        batch_id="BAT999999",
        location_id="BIN000001",
        quantity=1,
    )
    missing_bin = post_command(
        client,
        "missing-bin",
        kind="receive",
        batch_id="BAT000001",
        location_id="BIN999999",
        quantity=1,
    )
    release = post_command(
        client,
        "empty-release",
        kind="release",
        batch_id="BAT000001",
        location_id="BIN000001",
        quantity=1,
    )

    assert missing_batch.status_code == 404
    assert missing_bin.status_code == 404
    assert release.status_code == 409
    assert release.json["type"] == "insufficient-quantity"
    assert clean_inventory_database.inventory_operations.count_documents({}) == 0
    assert clean_inventory_database.inventory_holdings.count_documents({}) == 0
