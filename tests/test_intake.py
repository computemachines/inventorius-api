"""Focused tests for the low-friction physical capture loop."""

import pytest

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


def test_capture_creates_batch_operation_holding_and_observed_evidence(
    client, clean_inventory_database
):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {},
        "props": {},
    })

    response = client.post(
        "/api/intake",
        headers={"Idempotency-Key": "capture-resistors-1"},
        json={
            "description": "  10k resistors, probably 0603  ",
            "bin_id": "BIN000001",
            "quantity": 25,
            "observed_codes": [" RC0603-10K ", "RC0603-10K"],
        },
    )

    assert response.status_code == 201
    assert response.json["status"] == "item captured"
    assert response.json["state"] == {
        "sku_id": "SKU000001",
        "batch_id": "BAT000001",
        "operation_id": response.json["state"]["operation_id"],
        "bin_id": "BIN000001",
        "quantity": 25,
        "unit": "each",
        "description": "10k resistors, probably 0603",
        "observed_codes": ["RC0603-10K"],
        "provisional": True,
    }

    sku = clean_inventory_database.sku.find_one({"_id": "SKU000001"})
    assert sku["name"] == "10k resistors, probably 0603"
    assert sku["props"]["_capture_status"] == "provisional"
    assert sku["props"]["_captured_at"].endswith("+00:00")

    batch = clean_inventory_database.batch.find_one({"_id": "BAT000001"})
    assert batch["sku_id"] == "SKU000001"
    operation = clean_inventory_database.inventory_operations.find_one({})
    assert operation["kind"] == "receive"
    assert operation["legs"][0]["batch_id"] == "BAT000001"
    assert operation["legs"][0]["quantity"].to_decimal() == 25
    holding = clean_inventory_database.inventory_holdings.find_one({})
    assert holding["batch_id"] == "BAT000001"
    assert holding["location_id"] == "BIN000001"
    assert holding["quantity"].to_decimal() == 25
    observation = clean_inventory_database.inventory_code_observations.find_one({})
    assert observation["code"] == "RC0603-10K"
    assert observation["batch_id"] == "BAT000001"

    # The legacy bin projection is read-only to this clean-break path.
    bin_document = clean_inventory_database.bin.find_one({"_id": "BIN000001"})
    assert bin_document["contents"] == {}
    assert "_ledger_write_lock" not in bin_document

    assert client.get("/api/batch/BAT000001/bins").json["state"] == {
        "BIN000001": {"BAT000001": 25},
    }
    assert client.get("/api/sku/SKU000001/bins").json["state"] == {
        "BIN000001": {"SKU000001": 25},
    }
    assert client.get("/api/bin/BIN000001").json["state"]["contents"] == {
        "BAT000001": 25,
    }
    # A ledger-referenced location is not force-deletable.  This is a state
    # conflict, not a prompt to override safety with another query parameter.
    assert client.delete("/api/bin/BIN000001").status_code == 409
    assert client.delete("/api/bin/BIN000001?force=true").status_code == 409
    assert client.delete("/api/sku/SKU000001").status_code == 403
    assert client.delete("/api/batch/BAT000001").status_code == 403
    assert clean_inventory_database.sku.count_documents({"_id": "SKU000001"}) == 1
    assert clean_inventory_database.batch.count_documents({"_id": "BAT000001"}) == 1

    search = client.get("/api/search", query_string={"query": "resistors"})
    assert search.status_code == 200
    assert {result["id"] for result in search.json["state"]["results"]} == {
        "SKU000001", "BAT000001",
    }


def test_capture_observed_codes_find_the_batch_without_claiming_ownership(
    client, clean_inventory_database
):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {},
        "props": {},
    })

    response = client.post(
        "/api/intake",
        headers={"Idempotency-Key": "capture-probe-1"},
        json={
            "description": "Oscilloscope probe accessory",
            "observed_codes": ["0123456789012", "PROBE-SHEATH-01"],
            "bin_id": "BIN000001",
            "quantity": 1,
        },
    )

    assert response.status_code == 201
    assert response.json["state"]["observed_codes"] == [
        "0123456789012", "PROBE-SHEATH-01"
    ]

    batch = clean_inventory_database.batch.find_one({"_id": "BAT000001"})
    assert batch["owned_codes"] == []
    assert batch["associated_codes"] == []

    # This is an unrelated textual match.  An exact observed code must not
    # broaden into a generic search result.
    clean_inventory_database.sku.insert_one({
        "_id": "SKU000002",
        "name": "Fixture documented as 0123456789012",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })

    for code in ("0123456789012", "PROBE-SHEATH-01"):
        search = client.get("/api/search", query_string={"query": code})
        assert search.status_code == 200
        assert search.json["state"]["total_num_results"] == 1
        assert {
            result["id"] for result in search.json["state"]["results"]
        } == {"BAT000001"}

    usage = client.get("/api/codes/0123456789012/usage")
    assert usage.status_code == 200
    assert usage.json == {
        "code": "0123456789012",
        "usedBy": [{
            "id": "BAT000001",
            "name": "Oscilloscope probe accessory",
            "relationship": "observed",
            "type": "batch",
        }],
    }


def test_capture_rejects_missing_bin_without_creating_sku(client, clean_inventory_database):
    response = client.post("/api/intake", headers={"Idempotency-Key": "missing-bin"}, json={
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
        response = client.post("/api/intake", headers={"Idempotency-Key": "bad"})
    else:
        response = client.post("/api/intake", headers={"Idempotency-Key": "bad"}, json=body)

    assert response.status_code == 400
    assert response.json["type"] == "validation-error"
    assert clean_inventory_database.sku.count_documents({}) == 0


def test_capture_requires_an_idempotency_key(client, clean_inventory_database):
    response = client.post("/api/intake", json={
        "description": "capacitor", "bin_id": "BIN000001", "quantity": 1,
    })

    assert response.status_code == 400
    assert clean_inventory_database.inventory_operations.count_documents({}) == 0


def test_capture_replay_returns_original_state_without_new_documents(
    client, clean_inventory_database
):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000001", "contents": {}, "props": {},
    })
    payload = {
        "description": "mystery capacitor",
        "bin_id": "BIN000001",
        "quantity": 3,
        "observed_codes": ["X-1", "X-2"],
    }
    first = client.post("/api/intake", headers={"Idempotency-Key": "again"}, json=payload)
    replay = client.post(
        "/api/intake",
        headers={"Idempotency-Key": "again"},
        json={**payload, "observed_codes": ["X-2", "X-1", "X-1"]},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert clean_inventory_database.sku.count_documents({}) == 1
    assert clean_inventory_database.batch.count_documents({}) == 1
    assert clean_inventory_database.inventory_operations.count_documents({}) == 1
    assert clean_inventory_database.inventory_holdings.count_documents({}) == 1


def test_capture_rejects_key_reuse_for_a_different_command(
    client, clean_inventory_database
):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000001", "contents": {}, "props": {},
    })
    headers = {"Idempotency-Key": "one-key"}
    assert client.post("/api/intake", headers=headers, json={
        "description": "capacitor", "bin_id": "BIN000001", "quantity": 1,
    }).status_code == 201
    response = client.post("/api/intake", headers=headers, json={
        "description": "resistor", "bin_id": "BIN000001", "quantity": 1,
    })

    assert response.status_code == 409
    assert clean_inventory_database.inventory_operations.count_documents({}) == 1


def test_debug_cors_allows_the_idempotency_header(client):
    from inventorius import app

    was_debug = app.debug
    app.debug = True
    try:
        response = client.options("/api/intake")
    finally:
        app.debug = was_debug

    assert "Idempotency-Key" in response.headers["Access-Control-Allow-Headers"]


def test_blank_search_is_an_empty_result_set(client):
    response = client.get("/api/search")

    assert response.status_code == 200
    assert response.json["state"]["results"] == []
    assert response.json["state"]["total_num_results"] == 0


def test_search_matches_fragments_and_human_label_shorthand(
    client, clean_inventory_database
):
    clean_inventory_database.bin.insert_one({
        "_id": "BIN000145",
        "contents": {},
        "props": {},
    })
    clean_inventory_database.sku.insert_one({
        "_id": "SKU000145",
        "name": "Handheld IR thermometer",
        "owned_codes": ["026000005623"],
        "associated_codes": [],
        "props": {},
    })
    clean_inventory_database.sku.insert_one({
        "_id": "SKU000146",
        "name": "Instructions mentioning 026000005623",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })

    barcode_response = client.get(
        "/api/search", query_string={"query": "026000005623"}
    )
    assert barcode_response.status_code == 200
    assert [
        result["id"] for result in barcode_response.json["state"]["results"]
    ] == ["SKU000145"]

    fragment_response = client.get(
        "/api/search", query_string={"query": "hand"}
    )
    assert fragment_response.status_code == 200
    assert [
        result["id"] for result in fragment_response.json["state"]["results"]
    ] == ["SKU000145"]

    shorthand_response = client.get(
        "/api/search", query_string={"query": "bin145"}
    )
    assert shorthand_response.status_code == 200
    assert shorthand_response.json["state"]["results"][0]["id"] == "BIN000145"

    numeric_response = client.get(
        "/api/search", query_string={"query": "145"}
    )
    assert {
        result["id"] for result in numeric_response.json["state"]["results"]
    } == {"BIN000145", "SKU000145"}
