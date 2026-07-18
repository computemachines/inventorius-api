"""Focused tests for the low-friction physical capture loop."""

import pytest

from inventorius.db import get_mongo_client


@pytest.fixture(autouse=True)
def clean_inventory_database():
    database = get_mongo_client().testing
    for collection in (database.admin, database.batch, database.bin, database.sku):
        collection.delete_many({})
    yield database
    for collection in (database.admin, database.batch, database.bin, database.sku):
        collection.delete_many({})


def test_capture_creates_searchable_sku_in_existing_bin(client, clean_inventory_database):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {},
        "props": {},
    })

    response = client.post("/api/intake", json={
        "description": "  10k resistors, probably 0603  ",
        "bin_id": "BIN000001",
        "quantity": 25,
    })

    assert response.status_code == 201
    assert response.json["status"] == "item captured"
    assert response.json["state"] == {
        "sku_id": "SKU000001",
        "bin_id": "BIN000001",
        "quantity": 25,
        "description": "10k resistors, probably 0603",
        "provisional": True,
    }

    sku = clean_inventory_database.sku.find_one({"_id": "SKU000001"})
    assert sku["name"] == "10k resistors, probably 0603"
    assert sku["props"]["_capture_status"] == "provisional"
    assert sku["props"]["_captured_at"].endswith("+00:00")

    bin_document = clean_inventory_database.bin.find_one({"_id": "BIN000001"})
    assert bin_document["contents"] == {"SKU000001": 25}

    search = client.get("/api/search", query_string={"query": "resistors"})
    assert search.status_code == 200
    assert search.json["state"]["total_num_results"] == 1
    assert search.json["state"]["results"][0]["id"] == "SKU000001"


def test_capture_rejects_missing_bin_without_creating_sku(client, clean_inventory_database):
    response = client.post("/api/intake", json={
        "description": "mystery connector",
        "bin_id": "BIN000404",
        "quantity": 1,
    })

    assert response.status_code == 404
    assert clean_inventory_database.sku.count_documents({}) == 0


@pytest.mark.parametrize("body", [
    {"description": "   ", "bin_id": "BIN000001", "quantity": 1},
    {"description": "capacitor", "bin_id": "BIN000001", "quantity": 0},
    {"description": "capacitor", "bin_id": "not-a-bin", "quantity": 1},
    None,
])
def test_capture_rejects_invalid_input(client, clean_inventory_database, body):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {},
        "props": {},
    })

    if body is None:
        response = client.post("/api/intake")
    else:
        response = client.post("/api/intake", json=body)

    assert response.status_code == 400
    assert response.json["type"] == "validation-error"
    assert clean_inventory_database.sku.count_documents({}) == 0


def test_blank_search_is_an_empty_result_set(client):
    response = client.get("/api/search")

    assert response.status_code == 200
    assert response.json["state"]["results"] == []
    assert response.json["state"]["total_num_results"] == 0
