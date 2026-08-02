"""End-to-end contract for uncertain capture, use, recount, and rebuild."""

import pytest

from inventorius.quantity_projection import rebuilt_quantity_heads
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_quantity_database():
    database = get_test_database()
    collections = (
        database.admin,
        database.auth_principals,
        database.auth_sessions,
        database.batch,
        database.bin,
        database.identifier_counters,
        database.inventory_code_observations,
        database.inventory_holdings,
        database.inventory_operations,
        database.quantity_heads,
        database.quantity_observations,
        database.resource_identifiers,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    database.bin.insert_one({"_id": "BIN000001", "contents": {}, "props": {}})
    yield database
    for collection in collections:
        collection.delete_many({})


def estimated_capture(client, *, key="estimate-fasteners", description="Bag of fasteners"):
    return client.post(
        "/api/intake",
        headers={"Idempotency-Key": key},
        json={
            "description": description,
            "bin_id": "BIN000001",
            "unit": "each",
            "quantity_claim": {
                "domain": "discrete",
                "basis": "estimated",
                "preferred": 50,
            },
        },
    )


def test_uncertain_capture_is_findable_without_fake_available_inventory(
    client, clean_quantity_database
):
    response = estimated_capture(client)

    assert response.status_code == 201
    state = response.json["state"]
    assert state["quantity_native"] is True
    assert state["quantity_claim"] == {
        "domain": "discrete",
        "basis": "estimated",
        "lower": 0,
        "preferred": 50,
        "upper": 100,
        "capacity": None,
    }
    assert clean_quantity_database.inventory_holdings.count_documents({}) == 0
    operation = clean_quantity_database.inventory_operations.find_one({})
    assert operation["fact_schema"] == {
        "name": "inventory.operation", "version": 2
    }
    assert operation["legs"] == []
    assert "quantity_0" not in str(operation)
    assert operation["quantity_effect"]["claim"]["preferred"] == {
        "numerator": "50", "denominator": "1"
    }
    assert clean_quantity_database.quantity_heads.count_documents({}) == 1

    holding = client.get(
        "/api/quantity-holdings", query_string={"batch_id": state["batch_id"]}
    )
    assert holding.status_code == 200
    resource = holding.json["state"]["holdings"][0]
    assert resource["holding"] == {
        "batch_id": state["batch_id"],
        "location_id": "BIN000001",
        "unit": "each",
        "packaging_configuration_id": None,
    }
    assert resource["accepted_book"] == {
        "status": "absent", "quantity": None, "unit": "each"
    }
    assert resource["feasible_physical"]["minimum"] == 0
    assert resource["feasible_physical"]["preferred"] == 50
    assert resource["feasible_physical"]["maximum"] == 100

    search = client.get("/api/search", query_string={"query": "fasteners"})
    locations = search.json["state"]["details"][state["batch_id"]]["locations"]
    assert locations == [{
        "location_id": "BIN000001",
        "batch_id": state["batch_id"],
        "quantity": None,
        "quantity_kind": "feasible-physical",
        "minimum": 0,
        "preferred": 50,
        "maximum": 100,
        "quantity_status": "feasible",
        "unit": "each",
        "packaging_configuration_id": None,
    }]


def test_capture_replay_does_not_duplicate_identity_or_stream(
    client, clean_quantity_database
):
    first = estimated_capture(client, key="lost-response")
    replay = estimated_capture(client, key="lost-response")

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert clean_quantity_database.sku.count_documents({}) == 1
    assert clean_quantity_database.batch.count_documents({}) == 1
    assert clean_quantity_database.inventory_operations.count_documents({}) == 1
    assert clean_quantity_database.quantity_heads.count_documents({}) == 1


def test_known_use_and_recount_narrow_the_same_retained_history(
    client, clean_quantity_database
):
    captured = estimated_capture(client).json["state"]
    identity = {
        "batch_id": captured["batch_id"],
        "location_id": captured["bin_id"],
        "unit": "each",
        "domain": "discrete",
    }
    used = client.post(
        "/api/quantity-withdrawals",
        headers={"Idempotency-Key": "used-forty"},
        json={**identity, "amount": 40},
    )
    assert used.status_code == 201
    assert used.json["state"]["holding"]["feasible_physical"] == {
        "status": "feasible",
        "minimum": 0,
        "maximum": 60,
        "preferred": None,
        "capacity": None,
        "unit": "each",
        "domain": "discrete",
        "conflict_fact_ids": [],
    }
    counted = client.post(
        "/api/quantity-observations",
        headers={"Idempotency-Key": "counted-twenty"},
        json={
            **identity,
            "claim": {
                "domain": "discrete",
                "basis": "counted",
                "lower": 20,
                "preferred": 20,
                "upper": 20,
            },
        },
    )
    assert counted.status_code == 201
    physical = counted.json["state"]["holding"]["feasible_physical"]
    assert physical["status"] == "feasible"
    assert physical["minimum"] == physical["maximum"] == 20
    assert len(counted.json["state"]["holding"]["history"]) == 3


def test_conflicting_recount_is_saved_until_operator_supersedes_bad_evidence(
    client, clean_quantity_database
):
    captured = estimated_capture(client).json["state"]
    identity = {
        "batch_id": captured["batch_id"],
        "location_id": captured["bin_id"],
        "unit": "each",
        "domain": "discrete",
    }
    client.post(
        "/api/quantity-withdrawals",
        headers={"Idempotency-Key": "used-forty"},
        json={**identity, "amount": 40},
    )
    conflict = client.post(
        "/api/quantity-observations",
        headers={"Idempotency-Key": "counted-seventy"},
        json={
            **identity,
            "claim": {
                "domain": "discrete",
                "basis": "counted",
                "lower": 70,
                "preferred": 70,
                "upper": 70,
            },
        },
    )
    assert conflict.status_code == 201
    physical = conflict.json["state"]["holding"]["feasible_physical"]
    assert physical["status"] == "conflict"
    assert len(physical["conflict_fact_ids"]) == 3
    assert clean_quantity_database.quantity_observations.count_documents({}) == 1

    opening_id = captured["operation_id"]
    replacement = client.post(
        "/api/quantity-observations",
        headers={"Idempotency-Key": "correct-bad-opening"},
        json={
            **identity,
            "supersedes_fact_id": opening_id,
            "claim": {
                "domain": "discrete",
                "basis": "estimated",
                "lower": 70,
                "preferred": 70,
                "upper": 70,
            },
        },
    )
    assert replacement.status_code == 201
    assert replacement.json["state"]["holding"]["feasible_physical"]["status"] == "feasible"
    assert clean_quantity_database.inventory_operations.count_documents({}) == 2
    assert clean_quantity_database.quantity_observations.count_documents({}) == 2


def test_exact_ledger_commands_cannot_bypass_quantity_managed_holding(
    client, clean_quantity_database
):
    captured = estimated_capture(client).json["state"]
    exact_receive = client.post(
        "/api/inventory-operations",
        headers={"Idempotency-Key": "fake-exact-receive"},
        json={
            "kind": "receive",
            "batch_id": captured["batch_id"],
            "location_id": captured["bin_id"],
            "quantity": 1,
            "unit": "each",
        },
    )

    assert exact_receive.status_code == 409
    assert exact_receive.json["type"] == "quantity-managed-holding"
    assert clean_quantity_database.inventory_holdings.count_documents({}) == 0
    assert clean_quantity_database.inventory_operations.count_documents({}) == 1


def test_continuous_capture_retains_exact_decimal_strings(
    client, clean_quantity_database
):
    response = client.post(
        "/api/intake",
        headers={"Idempotency-Key": "spool"},
        json={
            "description": "Part-used wire spool",
            "bin_id": "BIN000001",
            "unit": "meter",
            "quantity_claim": {
                "domain": "continuous",
                "basis": "estimated",
                "lower": "125.5",
                "preferred": "128.0",
                "upper": "130.25",
                "capacity": "150",
            },
        },
    )

    assert response.status_code == 201
    claim = response.json["state"]["quantity_claim"]
    assert claim["lower"] == "125.5"
    assert claim["preferred"] == 128
    assert claim["upper"] == "130.25"


def test_quantity_heads_are_rebuildable_from_facts(
    client, clean_quantity_database
):
    captured = estimated_capture(client).json["state"]
    comparison = rebuilt_quantity_heads(clean_quantity_database)
    assert comparison["is_consistent"] is True
    clean_quantity_database.quantity_heads.delete_many({})
    assert rebuilt_quantity_heads(clean_quantity_database)["is_consistent"] is False

    rebuilt = rebuilt_quantity_heads(clean_quantity_database, replace=True)
    assert rebuilt["is_consistent"] is True
    assert client.get(
        "/api/quantity-holdings",
        query_string={"batch_id": captured["batch_id"]},
    ).status_code == 200
