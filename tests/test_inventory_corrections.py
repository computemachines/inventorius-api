"""Receipt reads and constrained append-only correction proofs."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from bson.decimal128 import Decimal128
import pytest

from inventorius.inventory_repository import (
    CorrectionRejected,
    InventoryRepository,
)
from inventorius.ledger import (
    HoldingKey,
    HoldingLeg,
    InsufficientHolding,
    InventoryOperation,
    OperationKind,
)
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_correction_database():
    database = get_test_database()
    collections = (
        database.batch,
        database.bin,
        database.inventory_code_observations,
        database.inventory_holdings,
        database.inventory_operations,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    database.sku.insert_one({
        "_id": "SKU000001",
        "name": "Test SKU",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    database.batch.insert_one({
        "_id": "BAT000001",
        "sku_id": "SKU000001",
        "name": "Test batch",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    database.bin.insert_many([
        {"_id": "BIN000001", "contents": {}, "props": {}},
        {"_id": "BIN000002", "contents": {}, "props": {}},
        {"_id": "BIN000003", "contents": {}, "props": {}},
    ])
    yield database
    for collection in collections:
        collection.delete_many({})


def post_command(client, key, **command):
    return client.post(
        "/api/inventory-operations",
        headers={"Idempotency-Key": key},
        json=command,
    )


def receive(client, key="receive-original", *, quantity=5, location_id="BIN000001"):
    response = post_command(
        client,
        key,
        kind="receive",
        batch_id="BAT000001",
        location_id=location_id,
        quantity=quantity,
    )
    assert response.status_code == 201
    return response.json["state"]["operation_id"]


def correct(client, original_id, key, *, quantity, location_id):
    return client.post(
        f"/api/inventory-operations/{original_id}/corrections",
        headers={"Idempotency-Key": key},
        json={"quantity": quantity, "location_id": location_id},
    )


def holding_quantities(database):
    return {
        holding["location_id"]: holding["quantity"].to_decimal()
        for holding in database.inventory_holdings.find({})
    }


@pytest.mark.parametrize(
    "quantity, location_id, expected_legs, expected_holdings",
    [
        (3, "BIN000001", {("BIN000001", Decimal(-2))}, {
            "BIN000001": Decimal(3),
        }),
        (7, "BIN000001", {("BIN000001", Decimal(2))}, {
            "BIN000001": Decimal(7),
        }),
        (5, "BIN000002", {
            ("BIN000001", Decimal(-5)),
            ("BIN000002", Decimal(5)),
        }, {
            "BIN000001": Decimal(0),
            "BIN000002": Decimal(5),
        }),
    ],
)
def test_correction_replaces_simple_receive_quantity_or_destination(
    client,
    clean_correction_database,
    quantity,
    location_id,
    expected_legs,
    expected_holdings,
):
    original_id = receive(client)
    original_before = clean_correction_database.inventory_operations.find_one({
        "_id": original_id,
    })

    response = correct(
        client,
        original_id,
        "correct-original",
        quantity=quantity,
        location_id=location_id,
    )

    assert response.status_code == 201
    receipt = response.json["state"]
    assert receipt["kind"] == "correction"
    assert receipt["corrects_operation_id"] == original_id
    assert receipt["correction"] == {
        "correctable": False,
        "blocker": "correction-target",
    }
    correction_id = receipt["operation_id"]
    correction = clean_correction_database.inventory_operations.find_one({
        "_id": correction_id,
    })
    assert correction["corrects_operation_id"] == original_id
    assert correction["actor"] == {
        "actor_id": "owner",
        "actor_type": "owner",
    }
    assert correction["command"] == {
        "command_id": correction_id,
        "name": "inventory.correction",
        "idempotency_key": "correct-original",
        "request_fingerprint": correction["request_fingerprint"],
    }
    assert correction["causation"] == {"corrects": original_id}
    assert correction["result"]["mode"] == "replace-receipt"
    assert correction["result"]["original_state"] == {
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "quantity": 5,
        "unit": "each",
        "packaging_configuration_id": None,
    }
    assert correction["result"]["intended_state"] == {
        "batch_id": "BAT000001",
        "location_id": location_id,
        "quantity": quantity,
        "unit": "each",
        "packaging_configuration_id": None,
    }
    assert {
        (leg["location_id"], leg["quantity"].to_decimal())
        for leg in correction["legs"]
    } == expected_legs
    assert holding_quantities(clean_correction_database) == expected_holdings
    assert clean_correction_database.inventory_operations.find_one({
        "_id": original_id,
    }) == original_before
    assert all(
        bin_document["contents"] == {}
        for bin_document in clean_correction_database.bin.find({})
    )

    original_receipt = client.get(
        f"/api/inventory-operations/{original_id}"
    ).json["state"]
    assert original_receipt["corrected_by_operation_id"] == correction_id
    assert original_receipt["correction"] == {
        "correctable": False,
        "blocker": "already-corrected",
    }


def test_quantity_zero_neutralizes_duplicate_capture_without_deleting_history(
    client, clean_correction_database
):
    original_id = receive(client, quantity=2)

    response = correct(
        client,
        original_id,
        "neutralize-duplicate",
        quantity=0,
        location_id="BIN000001",
    )

    assert response.status_code == 201
    correction_id = response.json["state"]["operation_id"]
    assert clean_correction_database.inventory_operations.count_documents({}) == 2
    assert clean_correction_database.inventory_operations.find_one({
        "_id": original_id,
    }) is not None
    correction = clean_correction_database.inventory_operations.find_one({
        "_id": correction_id,
    })
    assert correction["corrects_operation_id"] == original_id
    assert [
        leg["quantity"].to_decimal() for leg in correction["legs"]
    ] == [Decimal(-2)]
    assert holding_quantities(clean_correction_database) == {
        "BIN000001": Decimal(0),
    }


def test_correction_preserves_batch_sku_observations_and_original_evidence(
    client, clean_correction_database
):
    received = post_command(
        client,
        "evidenced-receive",
        kind="receive",
        batch_id="BAT000001",
        location_id="BIN000001",
        quantity=2,
        observed_codes=["PHYSICAL-CODE"],
    )
    original_id = received.json["state"]["operation_id"]
    batch_before = clean_correction_database.batch.find_one({"_id": "BAT000001"})
    sku_before = clean_correction_database.sku.find_one({"_id": "SKU000001"})
    observations_before = list(
        clean_correction_database.inventory_code_observations.find({})
    )

    response = correct(
        client,
        original_id,
        "preserve-evidence",
        quantity=1,
        location_id="BIN000002",
    )

    assert response.status_code == 201
    assert clean_correction_database.batch.find_one({
        "_id": "BAT000001",
    }) == batch_before
    assert clean_correction_database.sku.find_one({
        "_id": "SKU000001",
    }) == sku_before
    assert list(
        clean_correction_database.inventory_code_observations.find({})
    ) == observations_before
    original = clean_correction_database.inventory_operations.find_one({
        "_id": original_id,
    })
    assert original["result"]["observed_codes"] == ["PHYSICAL-CODE"]


def test_correction_retry_replays_and_other_payload_or_key_cannot_correct_twice(
    client, clean_correction_database
):
    original_id = receive(client)
    first = correct(
        client,
        original_id,
        "lost-response",
        quantity=4,
        location_id="BIN000001",
    )
    replay = correct(
        client,
        original_id,
        "lost-response",
        quantity=4,
        location_id="BIN1",
    )
    conflicting_payload = correct(
        client,
        original_id,
        "lost-response",
        quantity=3,
        location_id="BIN000001",
    )
    second_key = correct(
        client,
        original_id,
        "fresh-key",
        quantity=4,
        location_id="BIN000001",
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert conflicting_payload.status_code == 409
    assert conflicting_payload.json["type"] == "duplicate-resource"
    assert second_key.status_code == 409
    assert second_key.json["type"] == "correction-rejected"
    assert second_key.json["blocker"] == "already-corrected"
    assert clean_correction_database.inventory_operations.count_documents({}) == 2
    assert holding_quantities(clean_correction_database) == {
        "BIN000001": Decimal(4),
    }


def test_racing_fresh_keys_cannot_both_correct_one_original(
    client, clean_correction_database
):
    original_id = receive(client)
    repository = InventoryRepository(clean_correction_database)
    start = Barrier(2)

    def attempt(key):
        start.wait(timeout=10)
        try:
            result = repository.correct_inventory_operation(
                original_id,
                {"quantity": 4, "location_id": "BIN000001"},
                idempotency_key=key,
            )
            return ("committed", result.result["operation_id"])
        except CorrectionRejected as error:
            return (error.code, None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, ("correction-a", "correction-b")))

    assert sorted(outcome[0] for outcome in outcomes) == [
        "already-corrected", "committed",
    ]
    assert clean_correction_database.inventory_operations.count_documents({
        "kind": "correction",
        "corrects_operation_id": original_id,
    }) == 1
    correction_index = (
        clean_correction_database.inventory_operations.index_information()[
            "inventory_operation_single_correction"
        ]
    )
    assert correction_index["unique"] is True
    assert correction_index["partialFilterExpression"] == {
        "kind": "correction",
        "corrects_operation_id": {"$type": "string"},
    }
    assert holding_quantities(clean_correction_database) == {
        "BIN000001": Decimal(4),
    }


def test_racing_same_key_replays_one_correction(
    client, clean_correction_database
):
    original_id = receive(client)
    start = Barrier(2)

    def attempt():
        repository = InventoryRepository(clean_correction_database)
        start.wait(timeout=10)
        return repository.correct_inventory_operation(
            original_id,
            {"quantity": 4, "location_id": "BIN000001"},
            idempotency_key="same-racing-correction",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))

    assert {result.result["operation_id"] for result in results} == {
        results[0].result["operation_id"],
    }
    assert sorted(result.replayed for result in results) == [False, True]
    assert clean_correction_database.inventory_operations.count_documents({
        "kind": "correction",
        "corrects_operation_id": original_id,
    }) == 1
    assert holding_quantities(clean_correction_database) == {
        "BIN000001": Decimal(4),
    }


def test_correction_and_release_race_cannot_both_spend_original_holding(
    client, clean_correction_database
):
    original_id = receive(client)
    start = Barrier(2)

    def correction_attempt():
        repository = InventoryRepository(clean_correction_database)
        start.wait(timeout=10)
        try:
            result = repository.correct_inventory_operation(
                original_id,
                {"quantity": 5, "location_id": "BIN000002"},
                idempotency_key="racing-correction",
            )
            return ("correction", "committed", result.result["operation_id"])
        except InsufficientHolding:
            return ("correction", "insufficient", None)

    def release_attempt():
        repository = InventoryRepository(clean_correction_database)
        start.wait(timeout=10)
        try:
            result = repository.execute_inventory_command(
                {
                    "kind": "release",
                    "batch_id": "BAT000001",
                    "location_id": "BIN000001",
                    "quantity": 5,
                    "unit": "each",
                    "packaging_configuration_id": None,
                },
                idempotency_key="racing-release",
            )
            return ("release", "committed", result.result["operation_id"])
        except InsufficientHolding:
            return ("release", "insufficient", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        correction_future = executor.submit(correction_attempt)
        release_future = executor.submit(release_attempt)
        outcomes = [correction_future.result(), release_future.result()]

    assert sorted(outcome[1] for outcome in outcomes) == [
        "committed",
        "insufficient",
    ]
    assert clean_correction_database.inventory_operations.count_documents({}) == 2
    quantities = holding_quantities(clean_correction_database)
    assert all(quantity >= 0 for quantity in quantities.values())
    assert quantities["BIN000001"] == 0

    committed_kind = next(
        kind for kind, status, _ in outcomes if status == "committed"
    )
    if committed_kind == "correction":
        assert quantities == {
            "BIN000001": Decimal(0),
            "BIN000002": Decimal(5),
        }
        assert clean_correction_database.inventory_operations.count_documents({
            "kind": "correction",
            "corrects_operation_id": original_id,
        }) == 1
    else:
        assert quantities == {"BIN000001": Decimal(0)}
        assert clean_correction_database.inventory_operations.count_documents({
            "kind": "release",
        }) == 1


def test_correction_refuses_debit_when_later_movement_consumed_original_holding(
    client, clean_correction_database
):
    original_id = receive(client)
    moved = post_command(
        client,
        "move-most-stock",
        kind="transfer",
        batch_id="BAT000001",
        source_location_id="BIN000001",
        destination_location_id="BIN000002",
        quantity=4,
    )
    assert moved.status_code == 201
    before = holding_quantities(clean_correction_database)

    response = correct(
        client,
        original_id,
        "too-late-to-neutralize",
        quantity=0,
        location_id="BIN000001",
    )

    assert response.status_code == 409
    assert response.json["type"] == "insufficient-quantity"
    assert clean_correction_database.inventory_operations.count_documents({}) == 2
    assert holding_quantities(clean_correction_database) == before
    assert clean_correction_database.inventory_operations.count_documents({
        "kind": "correction",
    }) == 0


def test_noop_unknown_and_non_receive_receipts_are_rejected(
    client, clean_correction_database
):
    original_id = receive(client)
    unchanged = correct(
        client,
        original_id,
        "unchanged",
        quantity=5,
        location_id="BIN1",
    )
    unknown = correct(
        client,
        "OPffffffffffffffffffffffffffffffff",
        "unknown",
        quantity=1,
        location_id="BIN000001",
    )
    transfer = post_command(
        client,
        "move-one",
        kind="transfer",
        batch_id="BAT000001",
        source_location_id="BIN000001",
        destination_location_id="BIN000002",
        quantity=1,
    )
    transfer_id = transfer.json["state"]["operation_id"]
    unsupported = correct(
        client,
        transfer_id,
        "correct-transfer",
        quantity=1,
        location_id="BIN000001",
    )

    assert unchanged.status_code == 409
    assert unchanged.json["blocker"] == "unchanged-intended-state"
    assert unknown.status_code == 404
    assert unsupported.status_code == 409
    assert unsupported.json["blocker"] == "unsupported-operation-kind"
    unsupported_receipt = client.get(
        f"/api/inventory-operations/{transfer_id}"
    ).json["state"]
    assert unsupported_receipt["correction"] == {
        "correctable": False,
        "blocker": "unsupported-operation-kind",
    }
    assert clean_correction_database.inventory_operations.count_documents({
        "kind": "correction",
    }) == 0


@pytest.mark.parametrize(
    "leg, blocker",
    [
        ({
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "unit": "case",
            "packaging_configuration_id": None,
            "quantity": Decimal128("1"),
        }, "unsupported-unit"),
        ({
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "unit": "each",
            "packaging_configuration_id": "PKG-CASE",
            "quantity": Decimal128("1"),
        }, "packaged-holding"),
        ({
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "unit": "each",
            "packaging_configuration_id": None,
            "quantity": Decimal128("1.5"),
        }, "unsupported-quantity"),
        ({"not": "a holding leg"}, "malformed-history"),
    ],
)
def test_unsupported_or_malformed_receive_history_is_visible_but_not_correctable(
    client, clean_correction_database, leg, blocker
):
    operation_id = "OP11111111111111111111111111111111"
    clean_correction_database.inventory_operations.insert_one({
        "_id": operation_id,
        "idempotency_key": f"raw-{blocker}",
        "request_fingerprint": f"fingerprint-{blocker}",
        "kind": "receive",
        "legs": [leg],
        "created_at": datetime.now(timezone.utc),
        "result": {"operation_id": operation_id, "kind": "receive"},
    })

    detail = client.get(f"/api/inventory-operations/{operation_id}")
    response = correct(
        client,
        operation_id,
        f"reject-{blocker}",
        quantity=1,
        location_id="BIN000001",
    )

    assert detail.status_code == 200
    assert detail.json["state"]["correction"] == {
        "correctable": False,
        "blocker": blocker,
    }
    assert response.status_code == 409
    assert response.json["blocker"] == blocker
    assert clean_correction_database.inventory_operations.count_documents({}) == 1


def test_missing_historical_time_and_quantity_are_not_invented(
    client, clean_correction_database
):
    operation_id = "OP33333333333333333333333333333333"
    clean_correction_database.inventory_operations.insert_one({
        "_id": operation_id,
        "idempotency_key": "raw-missing-receipt-fields",
        "request_fingerprint": "fingerprint-missing-receipt-fields",
        "kind": "receive",
        "legs": [{
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "unit": "each",
            "packaging_configuration_id": None,
        }],
        "result": {"operation_id": operation_id, "kind": "receive"},
    })

    detail = client.get(f"/api/inventory-operations/{operation_id}")

    assert detail.status_code == 200
    assert detail.json["state"]["created_at"] is None
    assert detail.json["state"]["legs"][0]["quantity"] is None
    assert detail.json["state"]["correction"] == {
        "correctable": False,
        "blocker": "unsupported-quantity",
    }


def test_recent_and_detail_receipts_are_ordered_exact_sanitized_and_no_cache(
    client, clean_correction_database
):
    first_id = receive(client, "first-receipt", quantity=2)
    first_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    clean_correction_database.inventory_operations.update_one(
        {"_id": first_id},
        {
            "$set": {
                "created_at": first_time,
                "result.idempotency_key": "must-not-leak",
                "result.request_fingerprint": "must-not-leak",
                "result.unrelated_secret": "must-not-leak",
            }
        },
    )
    second_id = receive(client, "second-receipt", quantity=3)

    recent = client.get("/api/inventory-operations?limit=2")
    limited = client.get("/api/inventory-operations?limit=1")
    detail = client.get(f"/api/inventory-operations/{first_id}")

    assert recent.status_code == 200
    assert recent.headers["Cache-Control"] == "no-cache"
    operations = recent.json["state"]["operations"]
    assert [receipt["operation_id"] for receipt in operations] == [
        second_id, first_id,
    ]
    assert len(limited.json["state"]["operations"]) == 1
    assert detail.status_code == 200
    assert detail.headers["Cache-Control"] == "no-cache"
    receipt = detail.json["state"]
    assert receipt["result"] == {
        "operation_id": first_id,
        "kind": "receive",
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "quantity": 2,
        "unit": "each",
        "packaging_configuration_id": None,
    }
    assert receipt["legs"] == [{
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "unit": "each",
        "packaging_configuration_id": None,
        "quantity": 2,
    }]
    assert receipt["batches"] == [{
        "batch_id": "BAT000001",
        "batch_name": "Test batch",
        "sku_id": "SKU000001",
        "sku_name": "Test SKU",
    }]
    assert receipt["current_holdings"] == [{
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "unit": "each",
        "packaging_configuration_id": None,
        "quantity": 5,
    }]
    serialized = detail.get_data(as_text=True)
    assert "idempotency_key" not in serialized
    assert "request_fingerprint" not in serialized
    assert "unrelated_secret" not in serialized


def test_historical_quantity_above_javascript_safe_integer_remains_exact(
    client, clean_correction_database
):
    operation_id = "OP22222222222222222222222222222222"
    exact_quantity = Decimal128("9007199254740992")
    now = datetime.now(timezone.utc)
    clean_correction_database.inventory_operations.insert_one({
        "_id": operation_id,
        "idempotency_key": "historical-large-receive",
        "request_fingerprint": "historical-large-fingerprint",
        "kind": "receive",
        "legs": [{
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "unit": "each",
            "packaging_configuration_id": None,
            "quantity": exact_quantity,
        }],
        "created_at": now,
        "result": {
            "operation_id": operation_id,
            "kind": "receive",
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "quantity": exact_quantity,
            "unit": "each",
            "packaging_configuration_id": None,
        },
    })
    clean_correction_database.inventory_holdings.insert_one({
        "batch_id": "BAT000001",
        "location_id": "BIN000001",
        "unit": "each",
        "packaging_configuration_id": None,
        "quantity": exact_quantity,
        "updated_at": now,
    })

    detail = client.get(f"/api/inventory-operations/{operation_id}")
    rejected = correct(
        client,
        operation_id,
        "neutralize-large-history",
        quantity=0,
        location_id="BIN000001",
    )

    assert detail.status_code == 200
    assert detail.json["state"]["legs"][0]["quantity"] == "9007199254740992"
    assert detail.json["state"]["result"]["quantity"] == "9007199254740992"
    assert detail.json["state"]["current_holdings"][0]["quantity"] == (
        "9007199254740992"
    )
    assert detail.json["state"]["correction"] == {
        "correctable": False,
        "blocker": "unsupported-quantity",
    }
    assert rejected.status_code == 409
    assert rejected.json["blocker"] == "unsupported-quantity"
    assert holding_quantities(clean_correction_database) == {
        "BIN000001": Decimal("9007199254740992"),
    }


def test_public_command_still_rejects_arbitrary_correction_and_bounds_input(
    client, clean_correction_database
):
    ordinary = post_command(
        client,
        "arbitrary-correction",
        kind="correction",
        batch_id="BAT000001",
        location_id="BIN000001",
        quantity=1,
    )
    original_id = receive(client)
    too_large = correct(
        client,
        original_id,
        "huge-correction",
        quantity=9_007_199_254_740_992,
        location_id="BIN000001",
    )

    assert ordinary.status_code == 400
    assert too_large.status_code == 400
    assert too_large.json["invalid-params"][0]["name"] == "quantity"
    assert clean_correction_database.inventory_operations.count_documents({}) == 1


def test_generic_repository_post_cannot_bypass_constrained_correction_command(
    clean_correction_database,
):
    repository = InventoryRepository(clean_correction_database)
    arbitrary = InventoryOperation(
        operation_id="OParbitrary-correction",
        idempotency_key="arbitrary-internal-correction",
        kind=OperationKind.CORRECTION,
        legs=(
            HoldingLeg(
                HoldingKey("BAT000001", "BIN000001", "each"),
                -1,
            ),
        ),
        corrects_operation_id="OPmissing-original",
    )

    with pytest.raises(
        ValueError,
        match="must use the constrained correct_inventory_operation command",
    ):
        repository.post(
            arbitrary,
            request_fingerprint="arbitrary-fingerprint",
            result={"operation_id": arbitrary.operation_id},
        )

    assert clean_correction_database.inventory_operations.count_documents({}) == 0
    assert clean_correction_database.inventory_holdings.count_documents({}) == 0


@pytest.mark.parametrize("limit", ["0", "101", "all"])
def test_recent_receipt_limit_is_explicitly_bounded(
    client, clean_correction_database, limit
):
    response = client.get(f"/api/inventory-operations?limit={limit}")

    assert response.status_code == 400
    assert response.json["invalid-params"] == [{
        "name": "limit",
        "reason": "must be a whole number from 1 through 100",
    }]
