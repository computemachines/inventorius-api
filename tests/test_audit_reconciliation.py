"""Constrained append-only reconciliation of durable audit observations."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from threading import Barrier, Lock

from bson.decimal128 import Decimal128
import pytest

from inventorius.audit_snapshot import read_audit_snapshot
import inventorius.inventory_repository as inventory_repository_module
from inventorius.inventory_repository import (
    AuditReconciliationRejected,
    InventoryRepository,
)
from inventorius.ledger import (
    HoldingKey,
    HoldingLeg,
    InventoryOperation,
    OperationKind,
)
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def reconciliation_database():
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
        "props": {"zone": "reconciliation"},
    })
    database.batch.insert_many([
        {"_id": "BAT000001", "name": "Expected"},
        {"_id": "BAT000002", "name": "Unexpected but known"},
    ])
    yield database
    for collection in collections:
        collection.delete_many({})


def insert_holding(database, batch_id="BAT000001", quantity="5"):
    database.inventory_holdings.insert_one({
        "batch_id": batch_id,
        "location_id": "BIN000001",
        "unit": "each",
        "packaging_configuration_id": None,
        "quantity": Decimal128(quantity),
    })


def count(batch_id, quantity):
    return {
        "batch_id": batch_id,
        "quantity": quantity,
        "unit": "each",
        "packaging_configuration_id": None,
    }


def record_observation(
    client,
    database,
    counts,
    *,
    key="audit-before-reconciliation",
    unresolved_evidence=None,
):
    snapshot = read_audit_snapshot(database, "BIN000001")
    body = {
        "location_id": "BIN000001",
        "snapshot_token": snapshot["snapshot_token"],
        "counts": counts,
    }
    if unresolved_evidence is not None:
        body["unresolved_evidence"] = unresolved_evidence
    response = client.post(
        "/api/audit-observations",
        headers={"Idempotency-Key": key},
        json=body,
    )
    assert response.status_code == 201
    return response.json["state"]


def reconcile(client, observation_id, key, **body):
    return client.post(
        f"/api/audit-observations/{observation_id}/reconciliation",
        headers={"Idempotency-Key": key},
        json=body,
    )


def holding_quantities(database):
    return {
        holding["batch_id"]: holding["quantity"].to_decimal()
        for holding in database.inventory_holdings.find(
            {"quantity": {"$gt": Decimal128("0")}}
        )
    }


def test_reconciliation_applies_exact_differences_and_links_both_receipts(
    client,
    reconciliation_database,
):
    insert_holding(reconciliation_database)
    observation = record_observation(
        client,
        reconciliation_database,
        [count("BAT000001", 3), count("BAT000002", 2)],
    )
    observation_document_before = deepcopy(
        reconciliation_database.audit_observations.find_one({
            "_id": observation["observation_id"],
        })
    )
    bin_before = deepcopy(
        reconciliation_database.bin.find_one({"_id": "BIN000001"})
    )

    response = reconcile(
        client,
        observation["observation_id"],
        "apply-audit-variance",
        reason="unexplained-variance",
        note="  Counted twice before accepting.  ",
    )

    assert response.status_code == 201
    assert response.json["status"] == "audit observation reconciled"
    receipt = response.json["state"]
    operation_id = receipt["operation_id"]
    assert receipt["kind"] == "reconciliation"
    assert receipt["reconciles_observation_id"] == observation["observation_id"]
    assert receipt["corrects_operation_id"] is None
    assert receipt["legs"] == [
        {
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "unit": "each",
            "packaging_configuration_id": None,
            "quantity": -2,
        },
        {
            "batch_id": "BAT000002",
            "location_id": "BIN000001",
            "unit": "each",
            "packaging_configuration_id": None,
            "quantity": 2,
        },
    ]
    assert receipt["result"] == {
        "operation_id": operation_id,
        "kind": "reconciliation",
        "mode": "accept-physical-count",
        "observation_id": observation["observation_id"],
        "location_id": "BIN000001",
        "snapshot_token": observation["snapshot_token"],
        "reason": "unexplained-variance",
        "note": "Counted twice before accepting.",
        "boundary": "unexplained-inventory-variance",
    }
    assert holding_quantities(reconciliation_database) == {
        "BAT000001": Decimal(3),
        "BAT000002": Decimal(2),
    }
    assert reconciliation_database.audit_observations.find_one({
        "_id": observation["observation_id"],
    }) == observation_document_before
    assert reconciliation_database.bin.find_one({
        "_id": "BIN000001",
    }) == bin_before

    stored_operation = reconciliation_database.inventory_operations.find_one({
        "_id": operation_id,
    })
    assert stored_operation["reconciles_observation_id"] == (
        observation["observation_id"]
    )
    assert len(stored_operation["request_fingerprint"]) == 64
    assert "idempotency_key" not in str(receipt)
    assert "request_fingerprint" not in str(receipt)

    fetched_observation = client.get(
        f"/api/audit-observations/{observation['observation_id']}"
    )
    recent_observations = client.get("/api/audit-observations?limit=1")
    fetched_receipt = client.get(f"/api/inventory-operations/{operation_id}")
    assert fetched_observation.json["state"] == {
        **observation,
        "reconciled_by_operation_id": operation_id,
    }
    assert recent_observations.json["state"]["observations"] == [{
        **observation,
        "reconciled_by_operation_id": operation_id,
    }]
    assert fetched_receipt.json["state"] == receipt


def test_lost_reply_replays_and_second_reconciliation_is_refused(
    client,
    reconciliation_database,
):
    insert_holding(reconciliation_database)
    observation = record_observation(
        client,
        reconciliation_database,
        [count("BAT000001", 4)],
    )
    body = {
        "reason": "unexplained-variance",
        "note": "One item missing",
    }

    first = reconcile(
        client,
        observation["observation_id"],
        "reconciliation-retry",
        **body,
    )
    replay = reconcile(
        client,
        observation["observation_id"],
        "reconciliation-retry",
        **body,
    )
    changed = reconcile(
        client,
        observation["observation_id"],
        "reconciliation-retry",
        reason="unexplained-variance",
        note="Different request",
    )
    second_key = reconcile(
        client,
        observation["observation_id"],
        "different-reconciliation",
        **body,
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert changed.status_code == 409
    assert changed.json["type"] == "duplicate-resource"
    assert second_key.status_code == 409
    assert second_key.json["type"] == "audit-reconciliation-rejected"
    assert second_key.json["blocker"] == "already-reconciled"
    assert reconciliation_database.inventory_operations.count_documents({
        "kind": "reconciliation",
    }) == 1
    assert holding_quantities(reconciliation_database) == {
        "BAT000001": Decimal(4),
    }


@pytest.mark.parametrize(
    "counts, unresolved_evidence, blocker",
    [
        ([count("BAT000001", 4)], ["UNKNOWN-CODE"], "unresolved-evidence"),
        ([count("BAT000001", 5)], [], "no-variance"),
    ],
)
def test_incomplete_or_matching_observation_is_not_reconciled(
    client,
    reconciliation_database,
    counts,
    unresolved_evidence,
    blocker,
):
    insert_holding(reconciliation_database)
    observation = record_observation(
        client,
        reconciliation_database,
        counts,
        key=f"observation-{blocker}",
        unresolved_evidence=unresolved_evidence,
    )

    response = reconcile(
        client,
        observation["observation_id"],
        f"reconciliation-{blocker}",
        reason="unexplained-variance",
    )

    assert response.status_code == 409
    assert response.json["type"] == "audit-reconciliation-rejected"
    assert response.json["blocker"] == blocker
    assert reconciliation_database.inventory_operations.count_documents({}) == 0
    assert holding_quantities(reconciliation_database) == {
        "BAT000001": Decimal(5),
    }


@pytest.mark.parametrize("change, blocker", [
    (
        lambda database: database.inventory_holdings.update_one(
            {"batch_id": "BAT000001"},
            {"$set": {"quantity": Decimal128("6")}},
        ),
        "snapshot-stale",
    ),
    (
        lambda database: database.bin.update_one(
            {"_id": "BIN000001"},
            {"$set": {"contents": {"BAT000099": 1}}},
        ),
        "snapshot-blocked",
    ),
])
def test_current_inventory_must_still_match_the_observation(
    client,
    reconciliation_database,
    change,
    blocker,
):
    insert_holding(reconciliation_database)
    observation = record_observation(
        client,
        reconciliation_database,
        [count("BAT000001", 4)],
        key=f"observation-before-{blocker}",
    )
    change(reconciliation_database)
    before = holding_quantities(reconciliation_database)

    response = reconcile(
        client,
        observation["observation_id"],
        f"reconciliation-after-{blocker}",
        reason="unexplained-variance",
    )

    assert response.status_code == 409
    assert response.json["blocker"] == blocker
    assert reconciliation_database.inventory_operations.count_documents({}) == 0
    assert holding_quantities(reconciliation_database) == before


def test_command_validates_identity_disposition_and_missing_resources(
    client,
    reconciliation_database,
):
    invalid_id = client.post(
        "/api/audit-observations/not-an-observation/reconciliation",
        headers={"Idempotency-Key": "invalid-id"},
        json={"reason": "unexplained-variance"},
    )
    missing_key = client.post(
        f"/api/audit-observations/{'AOB' + '0' * 32}/reconciliation",
        json={"reason": "unexplained-variance"},
    )
    invalid_reason = reconcile(
        client,
        "AOB" + "0" * 32,
        "invalid-reason",
        reason="probably-the-cat",
    )
    missing_observation = reconcile(
        client,
        "AOB" + "0" * 32,
        "missing-observation",
        reason="unexplained-variance",
    )

    assert invalid_id.status_code == 400
    assert invalid_id.json["invalid-params"][0]["name"] == "observation_id"
    assert missing_key.status_code == 400
    assert missing_key.json["invalid-params"][0]["name"] == "Idempotency-Key"
    assert invalid_reason.status_code == 400
    assert invalid_reason.json["invalid-params"][0]["name"] == "reason"
    assert missing_observation.status_code == 404
    assert reconciliation_database.inventory_operations.count_documents({}) == 0


def test_internal_kind_cannot_widen_generic_operation_writes(
    client,
    reconciliation_database,
):
    generic_api = client.post(
        "/api/inventory-operations",
        headers={"Idempotency-Key": "arbitrary-reconciliation"},
        json={
            "kind": "reconciliation",
            "batch_id": "BAT000001",
            "location_id": "BIN000001",
            "quantity": 1,
        },
    )
    assert generic_api.status_code == 400

    repository = InventoryRepository(reconciliation_database)
    arbitrary = InventoryOperation(
        operation_id="OParbitrary-reconciliation",
        idempotency_key="arbitrary-internal-reconciliation",
        kind=OperationKind.RECONCILIATION,
        legs=(
            HoldingLeg(
                HoldingKey("BAT000001", "BIN000001", "each"),
                1,
            ),
        ),
        reconciles_observation_id="AOB" + "0" * 32,
    )
    with pytest.raises(ValueError, match="reconcile_audit_observation"):
        repository.post(
            arbitrary,
            request_fingerprint="not-publicly-derived",
            result={},
        )
    assert reconciliation_database.inventory_operations.count_documents({}) == 0
    assert reconciliation_database.inventory_holdings.count_documents({}) == 0


def test_oversized_legacy_observation_cannot_apply_a_rounded_difference(
    client,
    reconciliation_database,
):
    oversized = Decimal128("100000000000000000000000000009")
    insert_holding(
        reconciliation_database,
        quantity="100000000000000000000000000009",
    )
    observation_id = "AOB" + "1" * 32
    reconciliation_database.audit_observations.insert_one({
        "_id": observation_id,
        "idempotency_key": "legacy-oversized-observation",
        "request_fingerprint": "0" * 64,
        "location_id": "BIN000001",
        "snapshot_token": read_audit_snapshot(
            reconciliation_database,
            "BIN000001",
        )["snapshot_token"],
        "recorded_at": None,
        "counts": [{
            "batch_id": "BAT000001",
            "unit": "each",
            "packaging_configuration_id": None,
            "recorded_quantity": oversized,
            "observed_quantity": Decimal128("1"),
            # This is the lossy 28-digit result produced by the earlier code.
            "difference": Decimal128("-1.000000000000000000000000000E+29"),
        }],
        "unresolved_evidence": [],
    })

    response = reconcile(
        client,
        observation_id,
        "reject-legacy-rounded-difference",
        reason="unexplained-variance",
    )

    assert response.status_code == 409
    assert response.json["blocker"] == "malformed-observation"
    assert reconciliation_database.inventory_operations.count_documents({}) == 0
    assert holding_quantities(reconciliation_database) == {
        "BAT000001": oversized.to_decimal(),
    }


def test_nonfinite_stored_difference_is_rejected_without_mutation(
    client,
    reconciliation_database,
):
    insert_holding(reconciliation_database)
    observation_id = "AOB" + "2" * 32
    reconciliation_database.audit_observations.insert_one({
        "_id": observation_id,
        "idempotency_key": "malformed-nonfinite-observation",
        "request_fingerprint": "0" * 64,
        "location_id": "BIN000001",
        "snapshot_token": read_audit_snapshot(
            reconciliation_database,
            "BIN000001",
        )["snapshot_token"],
        "recorded_at": None,
        "counts": [{
            "batch_id": "BAT000001",
            "unit": "each",
            "packaging_configuration_id": None,
            "recorded_quantity": Decimal128("5"),
            "observed_quantity": Decimal128("3"),
            "difference": Decimal128("sNaN"),
        }],
        "unresolved_evidence": [],
    })
    observation_before = deepcopy(
        reconciliation_database.audit_observations.find_one({
            "_id": observation_id,
        })
    )
    bin_before = deepcopy(
        reconciliation_database.bin.find_one({"_id": "BIN000001"})
    )

    response = reconcile(
        client,
        observation_id,
        "reject-nonfinite-difference",
        reason="unexplained-variance",
    )

    assert response.status_code == 409
    assert response.json["blocker"] == "malformed-observation"
    assert reconciliation_database.inventory_operations.count_documents({}) == 0
    assert reconciliation_database.audit_observations.find_one({
        "_id": observation_id,
    }) == observation_before
    assert reconciliation_database.bin.find_one({
        "_id": "BIN000001",
    }) == bin_before
    assert holding_quantities(reconciliation_database) == {
        "BAT000001": Decimal(5),
    }


def test_racing_reconciliations_commit_exactly_once(
    client,
    reconciliation_database,
):
    insert_holding(reconciliation_database)
    observation = record_observation(
        client,
        reconciliation_database,
        [count("BAT000001", 2)],
    )

    def attempt(key):
        repository = InventoryRepository(reconciliation_database)
        try:
            result = repository.reconcile_audit_observation(
                observation["observation_id"],
                {"reason": "unexplained-variance"},
                idempotency_key=key,
            )
            return ("committed", result.result["operation_id"])
        except AuditReconciliationRejected as error:
            return (error.code, None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(
            attempt,
            ("racing-reconciliation-a", "racing-reconciliation-b"),
        ))

    assert sorted(outcome[0] for outcome in outcomes) == [
        "already-reconciled",
        "committed",
    ]
    assert reconciliation_database.inventory_operations.count_documents({
        "kind": "reconciliation",
    }) == 1
    assert holding_quantities(reconciliation_database) == {
        "BAT000001": Decimal(2),
    }


def test_reconciliation_and_receive_share_bin_serialization(
    client,
    reconciliation_database,
    monkeypatch,
):
    insert_holding(reconciliation_database)
    observation = record_observation(
        client,
        reconciliation_database,
        [count("BAT000001", 3)],
    )

    original_reserve = inventory_repository_module.reserve_inventory_resource
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
        inventory_repository_module,
        "reserve_inventory_resource",
        synchronized_reserve,
    )

    def reconciliation_attempt():
        repository = InventoryRepository(reconciliation_database)
        try:
            repository.reconcile_audit_observation(
                observation["observation_id"],
                {"reason": "unexplained-variance"},
                idempotency_key="reconciliation-racing-receive",
            )
            return "reconciled"
        except AuditReconciliationRejected as error:
            assert error.code == "snapshot-stale"
            return "snapshot-stale"

    def receive():
        repository = InventoryRepository(reconciliation_database)
        repository.execute_inventory_command(
            {
                "kind": "receive",
                # A different Batch makes the Bin the only shared write point.
                "batch_id": "BAT000002",
                "location_id": "BIN000001",
                "quantity": 1,
                "unit": "each",
                "packaging_configuration_id": None,
            },
            idempotency_key="receive-racing-reconciliation",
        )
        return "received"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = set(executor.map(
            lambda action: action(),
            (reconciliation_attempt, receive),
        ))

    assert outcomes in (
        {"received", "reconciled"},
        {"received", "snapshot-stale"},
    )
    operations = list(reconciliation_database.inventory_operations.find({}))
    assert {operation["kind"] for operation in operations} == (
        {"receive", "reconciliation"}
        if "reconciled" in outcomes
        else {"receive"}
    )
    assert holding_quantities(reconciliation_database) == (
        {
            "BAT000001": Decimal(3),
            "BAT000002": Decimal(1),
        }
        if "reconciled" in outcomes
        else {
            "BAT000001": Decimal(5),
            "BAT000002": Decimal(1),
        }
    )
