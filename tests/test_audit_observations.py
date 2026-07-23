"""HTTP and persistence proofs for durable physical-count observations."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import re
from threading import Barrier, Lock

from bson.decimal128 import Decimal128
import pytest

import inventorius.audit_observation as audit_observation_module
import inventorius.inventory_repository as inventory_repository_module
from inventorius.audit_observation import (
    AuditObservationRepository,
    AuditSnapshotStale,
)
from inventorius.audit_snapshot import read_audit_snapshot
from inventorius.inventory_repository import (
    InventoryRepository,
    LedgerReferencedBatch,
    LedgerReferencedBin,
)
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def audit_observation_database():
    database = get_test_database()
    collections = (
        database.audit_observations,
        database.batch,
        database.bin,
        database.inventory_code_observations,
        database.inventory_holdings,
        database.inventory_operations,
        database.resource_identifiers,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {},
        "props": {"zone": "audit"},
    })
    database.batch.insert_many([
        {"_id": "BAT000001", "name": "Expected"},
        {"_id": "BAT000002", "name": "Unexpected but known"},
    ])
    yield database
    for collection in collections:
        collection.delete_many({})


def insert_holding(
    database,
    batch_id="BAT000001",
    quantity="5",
    *,
    location_id="BIN000001",
    unit="each",
    packaging_configuration_id=None,
):
    database.inventory_holdings.insert_one({
        "batch_id": batch_id,
        "location_id": location_id,
        "unit": unit,
        "packaging_configuration_id": packaging_configuration_id,
        "quantity": Decimal128(quantity),
    })


def snapshot(database):
    return read_audit_snapshot(database, "BIN000001")


def count(
    batch_id,
    quantity,
    *,
    unit="each",
    packaging_configuration_id=None,
):
    return {
        "batch_id": batch_id,
        "quantity": quantity,
        "unit": unit,
        "packaging_configuration_id": packaging_configuration_id,
    }


def post_observation(client, key, body):
    return client.post(
        "/api/audit-observations",
        headers={"Idempotency-Key": key},
        json=body,
    )


def test_records_expected_and_unexpected_counts_without_mutating_inventory(
    client,
    audit_observation_database,
):
    insert_holding(audit_observation_database)
    current_snapshot = snapshot(audit_observation_database)
    holdings_before = deepcopy(list(
        audit_observation_database.inventory_holdings.find({})
    ))
    bin_before = deepcopy(
        audit_observation_database.bin.find_one({"_id": "BIN000001"})
    )

    response = post_observation(client, "reviewed-bin-1", {
        "location_id": " bin1 ",
        "snapshot_token": current_snapshot["snapshot_token"].upper(),
        "counts": [
            count("BAT2", 2),
            count("bat1", 3),
        ],
        "unresolved_evidence": [
            " loose label ",
            "loose label",
            "UNREADABLE-QR",
        ],
    })

    assert response.status_code == 201
    assert response.json["status"] == "audit observation recorded"
    state = response.json["state"]
    assert re.fullmatch(r"AOB[0-9a-f]{32}", state["observation_id"])
    assert state == {
        "observation_id": state["observation_id"],
        "location_id": "BIN000001",
        "snapshot_token": current_snapshot["snapshot_token"],
        "recorded_at": state["recorded_at"],
        "counts": [
            {
                "batch_id": "BAT000001",
                "unit": "each",
                "packaging_configuration_id": None,
                "recorded_quantity": 5,
                "observed_quantity": 3,
                "difference": -2,
            },
            {
                "batch_id": "BAT000002",
                "unit": "each",
                "packaging_configuration_id": None,
                "recorded_quantity": 0,
                "observed_quantity": 2,
                "difference": 2,
            },
        ],
        "unresolved_evidence": ["loose label", "UNREADABLE-QR"],
    }
    assert state["recorded_at"].endswith("+00:00")

    assert list(audit_observation_database.inventory_holdings.find({})) == (
        holdings_before
    )
    assert audit_observation_database.inventory_operations.count_documents({}) == 0
    assert audit_observation_database.bin.find_one(
        {"_id": "BIN000001"}
    ) == bin_before

    document = audit_observation_database.audit_observations.find_one({})
    assert document["idempotency_key"] == "reviewed-bin-1"
    assert len(document["request_fingerprint"]) == 64
    assert document["counts"][0]["recorded_quantity"].to_decimal() == Decimal(5)
    assert "idempotency_key" not in str(response.json)
    assert "request_fingerprint" not in str(response.json)

    fetched = client.get(
        f"/api/audit-observations/{state['observation_id']}"
    )
    recent = client.get("/api/audit-observations?limit=1")
    assert fetched.status_code == 200
    assert fetched.cache_control.no_cache
    assert fetched.json == {"state": state}
    assert recent.status_code == 200
    assert recent.json == {"state": {"observations": [state]}}


def test_canonical_retry_replays_and_changed_request_conflicts(
    client,
    audit_observation_database,
):
    insert_holding(audit_observation_database)
    token = snapshot(audit_observation_database)["snapshot_token"]
    first = post_observation(client, "audit-retry", {
        "location_id": "BIN1",
        "snapshot_token": token,
        "counts": [count("BAT2", 1), count("BAT1", 5)],
        "unresolved_evidence": ["second", "first", "second"],
    })
    replay = post_observation(client, "audit-retry", {
        "location_id": "bin000001",
        "snapshot_token": token.upper(),
        "counts": [count("bat000001", 5), count("BAT000002", 1)],
        "unresolved_evidence": ["first", "second"],
    })
    conflict = post_observation(client, "audit-retry", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT000001", 4), count("BAT000002", 1)],
        "unresolved_evidence": ["first", "second"],
    })

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert conflict.status_code == 409
    assert conflict.json["type"] == "duplicate-resource"
    assert audit_observation_database.audit_observations.count_documents({}) == 1


def test_successful_retry_survives_a_later_snapshot_change(
    client,
    audit_observation_database,
):
    insert_holding(audit_observation_database)
    token = snapshot(audit_observation_database)["snapshot_token"]
    body = {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT000001", 5)],
    }
    first = post_observation(client, "lost-success-response", body)
    audit_observation_database.inventory_holdings.update_one(
        {"batch_id": "BAT000001"},
        {"$set": {"quantity": Decimal128("6")}},
    )
    replay = post_observation(client, "lost-success-response", body)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert audit_observation_database.audit_observations.count_documents({}) == 1


def test_stale_snapshot_is_rejected_without_writing(
    client,
    audit_observation_database,
):
    insert_holding(audit_observation_database)
    stale_token = snapshot(audit_observation_database)["snapshot_token"]
    audit_observation_database.inventory_holdings.update_one(
        {"batch_id": "BAT000001"},
        {"$set": {"quantity": Decimal128("6")}},
    )
    current_token = snapshot(audit_observation_database)["snapshot_token"]

    response = post_observation(client, "stale-review", {
        "location_id": "BIN000001",
        "snapshot_token": stale_token,
        "counts": [count("BAT000001", 5)],
    })

    assert response.status_code == 409
    assert response.json["type"] == "audit-snapshot-stale"
    assert response.json["current_snapshot_token"] == current_token
    assert audit_observation_database.audit_observations.count_documents({}) == 0
    assert audit_observation_database.inventory_operations.count_documents({}) == 0


@pytest.mark.parametrize(
    "prepare",
    [
        lambda database: database.bin.update_one(
            {"_id": "BIN000001"},
            {"$set": {"contents": {"BAT000099": 1}}},
        ),
        lambda database: insert_holding(
            database,
            quantity="1.5",
        ),
    ],
)
def test_current_snapshot_blockers_prevent_an_observation(
    client,
    audit_observation_database,
    prepare,
):
    prepare(audit_observation_database)
    current_snapshot = snapshot(audit_observation_database)

    response = post_observation(client, "blocked-review", {
        "location_id": "BIN000001",
        "snapshot_token": current_snapshot["snapshot_token"],
        "counts": [],
    })

    assert response.status_code == 409
    assert response.json["type"] == "audit-snapshot-blocked"
    assert response.json["blockers"] == current_snapshot["blockers"]
    assert audit_observation_database.audit_observations.count_documents({}) == 0


def test_counts_require_exact_coverage_but_expected_zero_is_valid(
    client,
    audit_observation_database,
):
    insert_holding(audit_observation_database)
    token = snapshot(audit_observation_database)["snapshot_token"]

    missing = post_observation(client, "missing-expected", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [],
    })
    zero_expected = post_observation(client, "zero-expected", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT000001", 0)],
    })

    assert missing.status_code == 409
    assert missing.json["type"] == "audit-counts-rejected"
    assert missing.json["blocker"] == "missing-snapshot-holdings"
    assert zero_expected.status_code == 201
    assert zero_expected.json["state"]["counts"][0] == {
        "batch_id": "BAT000001",
        "unit": "each",
        "packaging_configuration_id": None,
        "recorded_quantity": 5,
        "observed_quantity": 0,
        "difference": -5,
    }


def test_unexpected_batch_must_be_known_currently_zero_and_positive(
    client,
    audit_observation_database,
):
    token = snapshot(audit_observation_database)["snapshot_token"]
    zero = post_observation(client, "unexpected-zero", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT000002", 0)],
    })
    missing = post_observation(client, "unexpected-missing", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT999999", 1)],
    })
    positive = post_observation(client, "unexpected-positive", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT000002", 2)],
    })

    assert zero.status_code == 409
    assert zero.json["blocker"] == "unexpected-count-not-positive"
    assert missing.status_code == 404
    assert missing.json["type"] == "missing-resource"
    assert positive.status_code == 201
    assert positive.json["state"]["counts"][0]["recorded_quantity"] == 0
    assert audit_observation_database.inventory_operations.count_documents({}) == 0
    assert audit_observation_database.inventory_holdings.count_documents({}) == 0


@pytest.mark.parametrize(
    "body, parameter",
    [
        ({
            "location_id": "BIN1",
            "snapshot_token": "x" * 64,
            "counts": [],
        }, "snapshot_token"),
        ({
            "location_id": "BIN1",
            "snapshot_token": "0" * 64,
            "counts": [count("BAT1", -1)],
        }, "quantity"),
        ({
            "location_id": "BIN1",
            "snapshot_token": "0" * 64,
            "counts": [count("BAT1", 1, unit="gram")],
        }, "unit"),
        ({
            "location_id": "BIN1",
            "snapshot_token": "0" * 64,
            "counts": [count(
                "BAT1",
                1,
                packaging_configuration_id="PACK-BOX",
            )],
        }, "packaging_configuration_id"),
    ],
)
def test_rejects_invalid_count_shapes(
    client,
    audit_observation_database,
    body,
    parameter,
):
    response = post_observation(client, f"invalid-{parameter}", body)

    assert response.status_code == 400
    assert response.json["type"] == "validation-error"
    expected_name = parameter if parameter == "snapshot_token" else "counts"
    assert response.json["invalid-params"][0]["name"] == expected_name
    assert audit_observation_database.audit_observations.count_documents({}) == 0


def test_rejects_duplicate_canonical_holding_identities_and_missing_key(
    client,
    audit_observation_database,
):
    token = snapshot(audit_observation_database)["snapshot_token"]
    duplicate = post_observation(client, "duplicate-counts", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT1", 1), count("BAT000001", 2)],
    })
    missing_key = client.post("/api/audit-observations", json={
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [],
    })

    assert duplicate.status_code == 400
    assert duplicate.json["invalid-params"][0]["name"] == "counts"
    assert missing_key.status_code == 400
    assert missing_key.json["invalid-params"][0]["name"] == "Idempotency-Key"
    assert audit_observation_database.audit_observations.count_documents({}) == 0


def test_observation_references_protect_bin_and_batch_deletion(
    client,
    audit_observation_database,
):
    token = snapshot(audit_observation_database)["snapshot_token"]
    recorded = post_observation(client, "deletion-reference", {
        "location_id": "BIN000001",
        "snapshot_token": token,
        "counts": [count("BAT000002", 1)],
    })
    assert recorded.status_code == 201

    repository = InventoryRepository(audit_observation_database)
    with pytest.raises(LedgerReferencedBin):
        repository.delete_legacy_bin("BIN000001", force=True)
    with pytest.raises(LedgerReferencedBatch):
        repository.delete_legacy_batch("BAT000002")

    assert audit_observation_database.bin.find_one({"_id": "BIN000001"})
    assert audit_observation_database.batch.find_one({"_id": "BAT000002"})


def test_observation_and_inventory_command_share_bin_serialization(
    audit_observation_database,
    monkeypatch,
):
    insert_holding(audit_observation_database)
    original_snapshot = snapshot(audit_observation_database)
    command = {
        "location_id": "BIN000001",
        "snapshot_token": original_snapshot["snapshot_token"],
        "counts": [count("BAT000001", 5)],
        "unresolved_evidence": [],
    }
    observation_repository = AuditObservationRepository(
        audit_observation_database
    )
    inventory_repository = InventoryRepository(audit_observation_database)

    original_reserve = audit_observation_module.reserve_inventory_resource
    start = Barrier(2)
    lock = Lock()
    bin_reservations = 0

    def synchronized_reserve(collection, resource_id, session):
        nonlocal bin_reservations
        if collection.name == "bin":
            with lock:
                bin_reservations += 1
                synchronize = bin_reservations <= 2
            if synchronize:
                start.wait(timeout=10)
        return original_reserve(collection, resource_id, session)

    monkeypatch.setattr(
        audit_observation_module,
        "reserve_inventory_resource",
        synchronized_reserve,
    )
    monkeypatch.setattr(
        inventory_repository_module,
        "reserve_inventory_resource",
        synchronized_reserve,
    )

    def observe():
        try:
            observation_repository.record(
                command,
                idempotency_key="concurrent-observation",
            )
            return "observed"
        except AuditSnapshotStale:
            return "stale"

    def receive():
        inventory_repository.execute_inventory_command(
            {
                "kind": "receive",
                # Use a different Batch so the Bin document is the only
                # serialization point shared by these two transactions.
                "batch_id": "BAT000002",
                "location_id": "BIN000001",
                "quantity": 1,
                "unit": "each",
                "packaging_configuration_id": None,
            },
            idempotency_key="concurrent-receive",
        )
        return "received"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = set(executor.map(lambda action: action(), (observe, receive)))

    assert "received" in outcomes
    assert outcomes in ({"received", "observed"}, {"received", "stale"})
    holdings = {
        holding["batch_id"]: holding["quantity"].to_decimal()
        for holding in audit_observation_database.inventory_holdings.find({})
    }
    assert holdings == {
        "BAT000001": Decimal(5),
        "BAT000002": Decimal(1),
    }
    assert audit_observation_database.inventory_operations.count_documents({}) == 1
    observation = audit_observation_database.audit_observations.find_one({})
    if "observed" in outcomes:
        assert observation["snapshot_token"] == original_snapshot["snapshot_token"]
        assert (
            observation["counts"][0]["recorded_quantity"].to_decimal()
            == Decimal(5)
        )
    else:
        assert observation is None
