"""HTTP proofs for the read-only physical-audit snapshot boundary."""

from copy import deepcopy

from bson.decimal128 import Decimal128
import pytest

from tests.database import get_test_database


@pytest.fixture(autouse=True)
def audit_database():
    database = get_test_database()
    collections = (
        database.audit_guard,
        database.batch,
        database.bin,
        database.inventory_holdings,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    yield database
    for collection in collections:
        collection.delete_many({})


def insert_holding(
    database,
    batch_id,
    quantity,
    *,
    location_id="BIN000001",
    unit="each",
    packaging_configuration_id=None,
):
    database.inventory_holdings.insert_one({
        "batch_id": batch_id,
        "location_id": location_id,
        "quantity": Decimal128(quantity),
        "unit": unit,
        "packaging_configuration_id": packaging_configuration_id,
    })


def get_snapshot(client, bin_id="BIN000001"):
    return client.get(f"/api/audit-snapshots/{bin_id}")


def database_state(database):
    names = sorted(database.list_collection_names())
    return {
        name: {
            "documents": deepcopy(
                list(database[name].find({}).sort("_id", 1))
            ),
            "indexes": deepcopy(database[name].index_information()),
        }
        for name in names
    }


def test_normalizes_bin_and_returns_sorted_positive_exact_holdings_with_names(
    client, audit_database
):
    audit_database.bin.insert_many([
        {"_id": "BIN000001", "contents": {}, "props": {}},
        {"_id": "BIN000002", "contents": {}, "props": {}},
    ])
    audit_database.sku.insert_many([
        {"_id": "SKU000001", "name": "Fasteners"},
        {"_id": "SKU000002", "name": "Adhesive"},
    ])
    audit_database.batch.insert_many([
        {"_id": "BAT000002", "sku_id": "SKU000002", "name": "Blue sticks"},
        {"_id": "BAT000001", "sku_id": "SKU000001", "name": "M3 screws"},
        {"_id": "BAT000003", "name": "Unclassified batch"},
    ])
    insert_holding(audit_database, "BAT000002", "2")
    insert_holding(audit_database, "BAT000001", "12")
    insert_holding(audit_database, "BAT000003", "0")
    insert_holding(
        audit_database,
        "BAT000003",
        "99",
        location_id="BIN000002",
    )

    response = get_snapshot(client, " bin1 ")

    assert response.status_code == 200
    assert response.cache_control.no_cache
    state = response.json["state"]
    assert state["location_id"] == "BIN000001"
    assert state["holdings"] == [
        {
            "batch_id": "BAT000001",
            "sku_id": "SKU000001",
            "batch_name": "M3 screws",
            "sku_name": "Fasteners",
            "quantity": 12,
            "unit": "each",
            "packaging_configuration_id": None,
            "supported": True,
        },
        {
            "batch_id": "BAT000002",
            "sku_id": "SKU000002",
            "batch_name": "Blue sticks",
            "sku_name": "Adhesive",
            "quantity": 2,
            "unit": "each",
            "packaging_configuration_id": None,
            "supported": True,
        },
    ]
    assert state["blockers"] == []
    assert len(state["snapshot_token"]) == 64


def test_token_ignores_names_but_changes_with_quantity_and_holding_shape(
    client, audit_database
):
    audit_database.bin.insert_one(
        {"_id": "BIN000001", "contents": {}, "props": {}}
    )
    audit_database.sku.insert_one({"_id": "SKU000001", "name": "Old SKU name"})
    audit_database.batch.insert_one({
        "_id": "BAT000001",
        "sku_id": "SKU000001",
        "name": "Old Batch name",
    })
    insert_holding(audit_database, "BAT000001", "2")

    original = get_snapshot(client).json["state"]["snapshot_token"]

    audit_database.sku.update_one(
        {"_id": "SKU000001"}, {"$set": {"name": "New SKU name"}}
    )
    audit_database.batch.update_one(
        {"_id": "BAT000001"}, {"$set": {"name": "New Batch name"}}
    )
    renamed = get_snapshot(client).json["state"]["snapshot_token"]

    audit_database.inventory_holdings.update_one(
        {"batch_id": "BAT000001"},
        {"$set": {"quantity": Decimal128("3")}},
    )
    changed_quantity = get_snapshot(client).json["state"]["snapshot_token"]

    audit_database.inventory_holdings.update_one(
        {"batch_id": "BAT000001"},
        {
            "$set": {
                "quantity": Decimal128("2"),
                "packaging_configuration_id": "PACK-BOX",
            }
        },
    )
    changed_shape = get_snapshot(client).json["state"]["snapshot_token"]

    assert renamed == original
    assert changed_quantity != original
    assert changed_shape != original


def test_reports_legacy_and_unsupported_shapes_without_collapsing_them(
    client, audit_database
):
    audit_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {"SKU000099": 4, "BAT000099": 1},
        "props": {},
    })
    for batch_id in ("BAT000001", "BAT000002", "BAT000003"):
        audit_database.batch.insert_one({"_id": batch_id})
    insert_holding(audit_database, "BAT000001", "1.5")
    insert_holding(audit_database, "BAT000002", "3", unit="gram")
    insert_holding(
        audit_database,
        "BAT000003",
        "1",
        packaging_configuration_id="PACK-SEALED",
    )

    state = get_snapshot(client).json["state"]

    assert [holding["supported"] for holding in state["holdings"]] == [
        False,
        False,
        False,
    ]
    # Blocker objects are deliberately summaries with stable machine fields.
    # The audit UI must not infer counts from legacy data or unsupported rows.
    assert state["blockers"] == [
        {"type": "legacy-bin-contents", "entry_count": 2},
        {"type": "unsupported-holding-shapes", "holding_count": 3},
    ]
    assert {
        holding["batch_id"] for holding in state["holdings"]
    } == {"BAT000001", "BAT000002", "BAT000003"}


def test_nonintegral_quantity_is_an_exact_string(client, audit_database):
    audit_database.bin.insert_one(
        {"_id": "BIN000001", "contents": {}, "props": {}}
    )
    audit_database.batch.insert_one({"_id": "BAT000001"})
    insert_holding(audit_database, "BAT000001", "1.2500")

    holding = get_snapshot(client).json["state"]["holdings"][0]

    assert holding["quantity"] == "1.2500"
    assert holding["supported"] is False


def test_missing_and_invalid_bin_ids_are_rejected(client, audit_database):
    missing = get_snapshot(client, "BIN404")
    invalid = get_snapshot(client, "SKU1")

    assert missing.status_code == 404
    assert missing.cache_control.no_cache
    assert missing.json["type"] == "missing-resource"
    assert invalid.status_code == 400
    assert invalid.cache_control.no_cache
    assert invalid.json["type"] == "validation-error"


def test_snapshot_request_does_not_mutate_any_collection(client, audit_database):
    audit_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {"BAT009999": 7},
        "props": {"zone": "bench"},
    })
    audit_database.batch.insert_one({
        "_id": "BAT000001",
        "sku_id": "SKU000001",
        "name": "Batch",
    })
    audit_database.sku.insert_one({"_id": "SKU000001", "name": "SKU"})
    insert_holding(audit_database, "BAT000001", "5")
    audit_database.audit_guard.insert_one(
        {"_id": "guard", "value": [1, 2, 3]}
    )
    before = database_state(audit_database)

    response = get_snapshot(client)

    assert response.status_code == 200
    assert database_state(audit_database) == before
