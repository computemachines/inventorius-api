"""Focused compatibility and truthfulness proofs for the general search API."""

from bson.decimal128 import Decimal128
import pytest

from tests.database import get_test_database


@pytest.fixture(autouse=True)
def search_database():
    database = get_test_database()
    collections = (
        database.batch,
        database.bin,
        database.inventory_code_observations,
        database.inventory_holdings,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    yield database
    for collection in collections:
        collection.delete_many({})


def insert_sku(database, sku_id, *, name=None, owned=(), associated=()):
    database.sku.insert_one({
        "_id": sku_id,
        "name": name,
        "owned_codes": list(owned),
        "associated_codes": list(associated),
        "props": {},
    })


def insert_batch(database, batch_id, *, sku_id=None, name=None):
    database.batch.insert_one({
        "_id": batch_id,
        "sku_id": sku_id,
        "name": name,
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })


def insert_holding(
    database,
    batch_id,
    location_id,
    quantity,
    *,
    unit="each",
    packaging_configuration_id=None,
):
    database.inventory_holdings.insert_one({
        "batch_id": batch_id,
        "location_id": location_id,
        "quantity": Decimal128(str(quantity)),
        "unit": unit,
        "packaging_configuration_id": packaging_configuration_id,
    })


def test_internal_labels_accept_optional_whitespace_and_explain_the_match(
    client, search_database
):
    search_database.bin.insert_one({
        "_id": "BIN000146", "contents": {}, "props": {}
    })

    response = client.get("/api/search", query_string={"query": " BIN 146 "})

    assert response.status_code == 200
    state = response.json["state"]
    assert [result["id"] for result in state["results"]] == ["BIN000146"]
    assert state["details"] == {
        "BIN000146": {
            "matched_by": [{
                "kind": "internal-label",
                "value": "BIN000146",
                "scope": "bin",
            }],
            "locations": [],
        },
    }


def test_exact_external_code_remains_strongest_and_explains_its_relationship(
    client, search_database
):
    code = "026000005623"
    insert_sku(search_database, "SKU000145", owned=[code])
    insert_sku(
        search_database,
        "SKU000146",
        name=f"Instructions mentioning {code}",
    )

    response = client.get("/api/search", query_string={"query": code})

    assert response.status_code == 200
    state = response.json["state"]
    assert [result["id"] for result in state["results"]] == ["SKU000145"]
    assert state["details"]["SKU000145"] == {
        "matched_by": [{
            "kind": "exact-code",
            "value": code,
            "scope": "sku",
            "relationship": "owned",
        }],
        "locations": [],
    }


def test_search_locations_keep_positive_ledger_holding_shapes_separate(
    client, search_database
):
    for bin_id in ("BIN000001", "BIN000002", "BIN000003"):
        search_database.bin.insert_one({
            "_id": bin_id, "contents": {}, "props": {}
        })
    insert_sku(search_database, "SKU000146", name="Workshop adhesive")
    insert_batch(search_database, "BAT000001", sku_id="SKU000146")
    insert_batch(search_database, "BAT000002", sku_id="SKU000146")
    insert_holding(search_database, "BAT000001", "BIN000002", 2)
    insert_holding(
        search_database,
        "BAT000001",
        "BIN000001",
        5,
        packaging_configuration_id="PKG000001",
    )
    insert_holding(search_database, "BAT000002", "BIN000003", "1.5", unit="gram")
    insert_holding(search_database, "BAT000002", "BIN000001", 0)
    insert_holding(search_database, "BAT000002", "BIN000002", -1)

    sku_response = client.get("/api/search", query_string={"query": "SKU 146"})
    assert sku_response.status_code == 200
    sku_detail = sku_response.json["state"]["details"]["SKU000146"]
    assert sku_detail["locations"] == [
        {
            "location_id": "BIN000001",
            "batch_id": "BAT000001",
            "quantity": 5,
            "unit": "each",
            "packaging_configuration_id": "PKG000001",
        },
        {
            "location_id": "BIN000002",
            "batch_id": "BAT000001",
            "quantity": 2,
            "unit": "each",
            "packaging_configuration_id": None,
        },
        {
            "location_id": "BIN000003",
            "batch_id": "BAT000002",
            "quantity": "1.5",
            "unit": "gram",
            "packaging_configuration_id": None,
        },
    ]

    batch_response = client.get("/api/search", query_string={"query": "BAT2"})
    assert batch_response.status_code == 200
    batch_detail = batch_response.json["state"]["details"]["BAT000002"]
    assert batch_detail["locations"] == [
        {
            "location_id": "BIN000003",
            "batch_id": "BAT000002",
            "quantity": "1.5",
            "unit": "gram",
            "packaging_configuration_id": None,
        },
    ]


def test_canonical_holdings_are_paginated_and_not_shadowed_by_external_codes(client, search_database):
    insert_sku(search_database, "SKU000001", name="Driver")
    insert_sku(search_database, "SKU000002", owned=["SKU000001"])
    insert_batch(search_database, "BAT000001", sku_id="SKU000001")
    insert_holding(search_database, "BAT000001", "BIN000001", "2.5", unit="m", packaging_configuration_id="spool")
    insert_holding(search_database, "BAT000001", "BIN000002", 4)
    response = client.get('/api/sku/SKU000001/holdings?limit=1&startingFrom=0')
    assert response.status_code == 200
    state = response.json['state']
    assert state['total_num_results'] == 2
    assert state['holdings'] == [{"location_id":"BIN000001", "batch_id":"BAT000001", "quantity":"2.5", "unit":"m", "packaging_configuration_id":"spool"}]
    second = client.get('/api/batch/BAT000001/holdings?limit=1&startingFrom=1').json['state']
    assert second['holdings'][0]['quantity'] == 4
    assert client.get('/api/sku/SKU999999/holdings').status_code == 404
    assert client.get('/api/bin/BIN000001/holdings').status_code == 404
