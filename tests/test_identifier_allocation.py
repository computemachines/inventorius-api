"""Regression tests for fixed-width monotonic identifier exhaustion."""

import pytest

from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_identifier_database():
    database = get_test_database()
    for collection in (
        database.admin,
        database.batch,
        database.bin,
        database.identifier_counters,
        database.inventory_counters,
        database.process_definition,
        database.resource_commands,
        database.resource_identifiers,
        database.sku,
    ):
        collection.delete_many({})
    yield database
    for collection in (
        database.admin,
        database.batch,
        database.bin,
        database.identifier_counters,
        database.inventory_counters,
        database.process_definition,
        database.resource_commands,
        database.resource_identifiers,
        database.sku,
    ):
        collection.delete_many({})


def assert_exhaustion_problem(response, prefix):
    assert response.status_code == 409
    assert response.mimetype == "application/problem+json"
    assert response.json == {
        "type": "identifier-space-exhausted",
        "title": "Identifier namespace is exhausted.",
        "prefix": prefix,
        "detail": f"No unused six-digit {prefix} identifiers remain.",
    }


def test_maximum_bin_id_is_valid_and_exhausts_monotonic_preview(
    client,
    clean_identifier_database,
):
    created = client.post(
        "/api/bins",
        headers={"Idempotency-Key": "maximum-bin"},
        json={"id": "BIN999999"},
    )

    assert created.status_code == 201
    assert clean_identifier_database.bin.find_one({"_id": "BIN999999"})

    counter = clean_identifier_database.admin.find_one({"_id": "BIN"})
    assert counter["used"] == [999999]
    assert counter["next"] is None
    assert counter["exhausted"] is True

    assert_exhaustion_problem(client.get("/api/next/bin"), "BIN")


@pytest.mark.parametrize(
    "prefix,path",
    [
        ("SKU", "/api/next/sku"),
        ("BAT", "/api/next/batch"),
        ("BIN", "/api/next/bin"),
    ],
)
def test_next_routes_share_the_exhaustion_contract(
    client,
    clean_identifier_database,
    prefix,
    path,
):
    clean_identifier_database.admin.insert_one({
        "_id": prefix,
        "next": f"{prefix}999999",
        "used": [999999],
    })

    assert_exhaustion_problem(client.get(path), prefix)


def test_process_definition_allocation_uses_the_exhaustion_contract(
    client,
    clean_identifier_database,
):
    clean_identifier_database.sku.insert_one({
        "_id": "SKU000001",
        "name": "Glue sticks",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    clean_identifier_database.admin.insert_one({
        "_id": "PRC",
        "next": "PRC999999",
        "used": [999999],
    })

    response = client.post("/api/process-definitions", json={
        "name": "Open case",
        "kind": "repackaging",
        "inputs": [{
            "role": "Case",
            "sku_id": "SKU000001",
            "quantity": 1,
            "unit": "case",
        }],
        "outputs": [{
            "role": "Items",
            "sku_id": "SKU000001",
            "quantity": 10,
            "unit": "each",
        }],
    })

    assert_exhaustion_problem(response, "PRC")
    assert clean_identifier_database.process_definition.count_documents({}) == 0
