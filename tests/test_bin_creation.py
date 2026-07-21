"""Proofs for durable, label-safe Bin creation."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from inventorius.bin_repository import BinRepository
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_bin_database():
    database = get_test_database()
    collections = (
        database.admin,
        database.bin,
        database.identifier_counters,
        database.inventory_holdings,
        database.inventory_operations,
        database.resource_commands,
        database.resource_identifiers,
    )
    for collection in collections:
        collection.delete_many({})
    yield database
    for collection in collections:
        collection.delete_many({})


def post_bin(client, key, body=None):
    return client.post(
        "/api/bins",
        headers={"Idempotency-Key": key},
        json={} if body is None else body,
    )


def test_bin_creation_requires_a_bounded_idempotency_key(client):
    missing = client.post("/api/bins", json={})
    oversized = post_bin(client, "x" * 201)

    assert missing.status_code == 400
    assert missing.json["invalid-params"] == [{
        "name": "Idempotency-Key",
        "reason": "header is required",
    }]
    assert oversized.status_code == 400
    assert oversized.json["invalid-params"] == [{
        "name": "Idempotency-Key",
        "reason": "must be at most 200 characters",
    }]


def test_server_allocates_bin_and_lost_response_replays_exact_state(
    client, clean_bin_database
):
    first = post_bin(client, "create-workbench-bin", {"props": {"zone": "bench"}})
    replay = post_bin(client, "create-workbench-bin", {"props": {"zone": "bench"}})

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert first.json["state"] == {
        "id": "BIN000001",
        "props": {"zone": "bench"},
    }
    assert first.json["Id"].endswith("/api/bin/BIN000001")
    assert clean_bin_database.bin.count_documents({}) == 1
    assert clean_bin_database.resource_identifiers.count_documents({}) == 1
    assert clean_bin_database.resource_commands.count_documents({}) == 1
    assert clean_bin_database.inventory_operations.count_documents({}) == 0


def test_same_key_rejects_a_different_request(client, clean_bin_database):
    assert post_bin(client, "one-command", {"props": {"shelf": 1}}).status_code == 201

    conflict = post_bin(client, "one-command", {"props": {"shelf": 2}})

    assert conflict.status_code == 409
    assert conflict.json["type"] == "duplicate-resource"
    assert conflict.json["invalid-params"] == [{
        "name": "Idempotency-Key",
        "reason": "must not be reused for a different request",
    }]
    assert clean_bin_database.bin.count_documents({}) == 1
    assert clean_bin_database.resource_commands.count_documents({}) == 1


def test_explicit_id_is_normalized_and_advances_server_allocation(
    client, clean_bin_database
):
    explicit = post_bin(client, "explicit-sixty", {"id": "bin60"})
    automatic = post_bin(client, "after-sixty")

    assert explicit.status_code == 201
    assert explicit.json["state"] == {"id": "BIN000060", "props": {}}
    assert automatic.status_code == 201
    assert automatic.json["state"]["id"] == "BIN000061"
    assert client.get("/api/next/bin").json["state"] == "BIN000062"


def test_initial_allocation_honors_admin_history_and_live_bins(
    client, clean_bin_database
):
    clean_bin_database.admin.insert_one({
        "_id": "BIN",
        "next": "BIN000008",
        "used": [2, 7],
        "exhausted": False,
    })
    clean_bin_database.bin.insert_one({
        "_id": "BIN000012", "contents": {}, "props": {},
    })

    created = post_bin(client, "after-legacy-state")

    assert created.status_code == 201
    assert created.json["state"]["id"] == "BIN000013"
    assert client.get("/api/next/bin").json["state"] == "BIN000014"


def test_historical_admin_used_id_cannot_be_reassigned(
    client, clean_bin_database
):
    clean_bin_database.admin.insert_one({
        "_id": "BIN",
        "next": "BIN000061",
        "used": [60],
        "exhausted": False,
    })

    conflict = post_bin(client, "reuse-deleted-legacy-id", {"id": "BIN60"})

    assert conflict.status_code == 409
    assert conflict.json["invalid-params"] == [{
        "name": "id", "reason": "has already been used",
    }]
    assert clean_bin_database.bin.count_documents({}) == 0
    assert clean_bin_database.resource_commands.count_documents({}) == 0


def test_identifier_remains_used_after_bin_deletion(client, clean_bin_database):
    created = post_bin(client, "create-then-delete", {"id": "BIN60"})
    assert created.status_code == 201
    assert client.delete("/api/bin/BIN60").status_code == 200

    conflict = post_bin(client, "new-meaning-for-old-label", {"id": "BIN60"})

    assert conflict.status_code == 409
    assert clean_bin_database.bin.count_documents({}) == 0
    assert clean_bin_database.resource_identifiers.find_one({
        "_id": "BIN000060"
    }) is not None


def test_deleting_a_pre_allocator_bin_creates_a_permanent_claim(
    client, clean_bin_database
):
    clean_bin_database.bin.insert_one({
        "_id": "BIN000099", "contents": {}, "props": {},
    })

    assert client.delete("/api/bin/BIN99").status_code == 200
    conflict = post_bin(client, "reuse-pre-allocator-bin", {"id": "BIN99"})

    assert conflict.status_code == 409
    assert clean_bin_database.resource_identifiers.find_one({
        "_id": "BIN000099"
    }) is not None


def test_failed_receipt_insert_rolls_back_bin_identifier_and_counter(
    clean_bin_database, monkeypatch
):
    repository = BinRepository(clean_bin_database)

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("simulate failure after Bin insert")

    monkeypatch.setattr(repository, "_insert_receipt", fail_receipt)
    with pytest.raises(RuntimeError, match="after Bin insert"):
        repository.create({}, idempotency_key="failed-create")

    assert clean_bin_database.bin.count_documents({}) == 0
    assert clean_bin_database.resource_identifiers.count_documents({}) == 0
    assert clean_bin_database.resource_commands.count_documents({}) == 0
    assert clean_bin_database.identifier_counters.count_documents({}) == 0
    assert clean_bin_database.admin.count_documents({}) == 0

    recovered = BinRepository(clean_bin_database).create(
        {}, idempotency_key="successful-create"
    )
    assert recovered.state["id"] == "BIN000001"


def test_concurrent_same_key_creates_one_bin_and_one_replay(clean_bin_database):
    repositories = (
        BinRepository(clean_bin_database),
        BinRepository(clean_bin_database),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda repository: repository.create(
                {"props": {"aisle": "A"}},
                idempotency_key="racing-browser-retry",
            ),
            repositories,
        ))

    assert {result.replayed for result in results} == {False, True}
    assert results[0].state == results[1].state
    assert clean_bin_database.bin.count_documents({}) == 1
    assert clean_bin_database.resource_identifiers.count_documents({}) == 1
    assert clean_bin_database.resource_commands.count_documents({}) == 1


def test_concurrent_distinct_commands_allocate_distinct_monotonic_ids(
    clean_bin_database
):
    repositories = (
        BinRepository(clean_bin_database),
        BinRepository(clean_bin_database),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda pair: pair[0].create({}, idempotency_key=pair[1]),
            zip(repositories, ("first-browser-command", "second-browser-command")),
        ))

    assert {result.state["id"] for result in results} == {
        "BIN000001", "BIN000002",
    }
    assert all(not result.replayed for result in results)
    assert clean_bin_database.bin.count_documents({}) == 2
    assert BinRepository(clean_bin_database).next_available_id() == "BIN000003"


def test_resource_receipt_of_another_kind_is_not_replayed(
    client, clean_bin_database
):
    clean_bin_database.resource_commands.insert_one({
        "idempotency_key": "shared-key",
        "request_fingerprint": "unrelated",
        "kind": "some-future-command",
        "result": {"id": "OTHER"},
    })

    conflict = post_bin(client, "shared-key")

    assert conflict.status_code == 409
    assert conflict.json["invalid-params"][0]["name"] == "Idempotency-Key"
    assert clean_bin_database.bin.count_documents({}) == 0


def test_server_allocation_reports_fixed_width_exhaustion(
    client, clean_bin_database
):
    maximum = post_bin(client, "last-bin", {"id": "BIN999999"})
    exhausted = post_bin(client, "one-too-many")

    assert maximum.status_code == 201
    assert exhausted.status_code == 409
    assert exhausted.json["type"] == "identifier-space-exhausted"
    assert clean_bin_database.bin.count_documents({}) == 1
    assert clean_bin_database.resource_commands.count_documents({}) == 1
    assert client.get("/api/next/bin").status_code == 409
