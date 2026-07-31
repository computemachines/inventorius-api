"""Proofs for the shared BIN/SKU/BAT identity boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from inventorius.inventory_repository import (
    InventoryRepository,
    LedgerReferencedSku,
)
from inventorius.resource_repository import (
    ALLOCATOR_MARKER,
    MissingResourceReference,
    ResourceRepository,
)
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_resource_database():
    database = get_test_database()
    collections = (
        database.admin,
        database.batch,
        database.bin,
        database.identifier_counters,
        database.inventory_code_observations,
        database.inventory_counters,
        database.inventory_holdings,
        database.inventory_operations,
        database.resource_commands,
        database.resource_identifiers,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    yield database
    for collection in collections:
        collection.delete_many({})


def post_sku(client, key, body=None):
    return client.post(
        "/api/skus",
        headers={"Idempotency-Key": key},
        json={} if body is None else body,
    )


def post_batch(client, key, body=None):
    return client.post(
        "/api/batches",
        headers={"Idempotency-Key": key},
        json={} if body is None else body,
    )


@pytest.mark.parametrize("prefix", ["bin", "sku", "batch"])
def test_legacy_next_preview_does_not_advertise_an_incomplete_create_operation(
    client, prefix
):
    response = client.get(f"/api/next/{prefix}")

    assert response.status_code == 200
    assert "operations" not in response.json


@pytest.mark.parametrize("path", ["/api/skus", "/api/batches"])
def test_sku_and_batch_creation_require_a_bounded_idempotency_key(client, path):
    missing = client.post(path, json={})
    oversized = client.post(
        path,
        headers={"Idempotency-Key": "x" * 201},
        json={},
    )

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


def test_sku_server_allocation_replays_and_persists_returned_state(
    client, clean_resource_database
):
    first = post_sku(client, "create-glue", {
        "name": "Hot glue sticks",
        "owned_codes": ["026000005623"],
    })
    replay = post_sku(client, "create-glue", {
        "name": "Hot glue sticks",
        "owned_codes": ["026000005623"],
        "associated_codes": [],
        "props": {},
    })
    conflict = post_sku(client, "create-glue", {
        "name": "Different product",
        "owned_codes": ["026000005623"],
    })

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert conflict.status_code == 409
    assert first.json == {
        "Id": "/api/sku/SKU000001",
        "status": "sku created",
        "state": {
            "id": "SKU000001",
            "owned_codes": ["026000005623"],
            "associated_codes": [],
            "name": "Hot glue sticks",
            "props": {},
        },
    }
    assert clean_resource_database.sku.find_one({"_id": "SKU000001"}) == {
        "_id": "SKU000001",
        "owned_codes": ["026000005623"],
        "associated_codes": [],
        "name": "Hot glue sticks",
        "props": {},
    }
    assert clean_resource_database.resource_commands.count_documents({}) == 1
    assert clean_resource_database.resource_commands.find_one({})["actor"] == {
        "actor_id": "owner", "actor_type": "owner",
    }
    assert clean_resource_database.resource_identifiers.count_documents({
        "_id": "SKU000001",
    }) == 1


def test_batch_server_allocation_replays_and_validates_sku_transactionally(
    client, clean_resource_database
):
    clean_resource_database.sku.insert_one({
        "_id": "SKU000007",
        "name": "Known product",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    payload = {
        "sku_id": "sku7",
        "name": "Receiving lot",
        "associated_codes": ["LOT-42"],
    }

    first = post_batch(client, "create-lot", payload)
    replay = post_batch(client, "create-lot", {
        **payload,
        "owned_codes": [],
        "props": {},
    })
    missing = post_batch(client, "missing-sku", {"sku_id": "SKU999999"})

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json == first.json
    assert first.json["state"] == {
        "id": "BAT000001",
        "sku_id": "SKU000007",
        "name": "Receiving lot",
        "owned_codes": [],
        "associated_codes": ["LOT-42"],
        "props": {},
    }
    assert clean_resource_database.batch.find_one({"_id": "BAT000001"}) == {
        "_id": "BAT000001",
        "sku_id": "SKU000007",
        "name": "Receiving lot",
        "owned_codes": [],
        "associated_codes": ["LOT-42"],
        "props": {},
    }
    assert missing.status_code == 400
    assert clean_resource_database.resource_commands.count_documents({}) == 1
    assert clean_resource_database.resource_identifiers.count_documents({
        "prefix": "BAT",
    }) == 1


def test_admin_creation_and_quick_capture_alternate_in_one_namespace(
    client, clean_resource_database
):
    clean_resource_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {},
        "props": {},
    })

    first_sku = post_sku(client, "admin-sku-1", {"name": "First"})
    capture_new = client.post(
        "/api/intake",
        headers={"Idempotency-Key": "capture-new"},
        json={
            "description": "Captured second SKU",
            "bin_id": "BIN000001",
            "quantity": 1,
        },
    )
    third_sku = post_sku(client, "admin-sku-3", {"name": "Third"})
    second_batch = post_batch(
        client,
        "admin-batch-2",
        {"sku_id": first_sku.json["state"]["id"], "name": "Admin batch"},
    )
    capture_existing = client.post(
        "/api/intake",
        headers={"Idempotency-Key": "capture-existing"},
        json={
            "sku_id": first_sku.json["state"]["id"],
            "bin_id": "BIN000001",
            "quantity": 1,
        },
    )

    assert first_sku.json["state"]["id"] == "SKU000001"
    assert capture_new.json["state"]["sku_id"] == "SKU000002"
    assert third_sku.json["state"]["id"] == "SKU000003"
    assert capture_new.json["state"]["batch_id"] == "BAT000001"
    assert second_batch.json["state"]["id"] == "BAT000002"
    assert capture_existing.json["state"]["batch_id"] == "BAT000003"
    assert {
        document["_id"]
        for document in clean_resource_database.resource_identifiers.find(
            {"prefix": "SKU"}
        )
    } == {"SKU000001", "SKU000002", "SKU000003"}
    assert {
        document["_id"]
        for document in clean_resource_database.resource_identifiers.find(
            {"prefix": "BAT"}
        )
    } == {"BAT000001", "BAT000002", "BAT000003"}
    for prefix, next_number in (("SKU", 4), ("BAT", 4)):
        assert clean_resource_database.identifier_counters.find_one({
            "_id": prefix,
        })["next_number"] == next_number
        assert clean_resource_database.inventory_counters.find_one({
            "_id": prefix,
        })["next_number"] == next_number
        assert clean_resource_database.admin.find_one({
            "_id": prefix,
        })["next"] == f"{prefix}00000{next_number}"


@pytest.mark.parametrize(
    "prefix,path,delete_path,collection_name",
    [
        ("SKU", "/api/skus", "/api/sku/{id}", "sku"),
        ("BAT", "/api/batches", "/api/batch/{id}", "batch"),
    ],
)
def test_deleted_resource_identifier_is_never_reused(
    client,
    clean_resource_database,
    prefix,
    path,
    delete_path,
    collection_name,
):
    post = post_sku if prefix == "SKU" else post_batch
    created = post(client, f"create-{prefix}", {})
    identifier = created.json["state"]["id"]
    assert client.delete(delete_path.format(id=identifier)).status_code in (200, 204)

    explicit_reuse = post(
        client,
        f"reuse-{prefix}",
        {"id": identifier},
    )
    next_created = post(client, f"next-{prefix}", {})

    assert explicit_reuse.status_code == 409
    assert next_created.json["state"]["id"] == f"{prefix}000002"
    assert clean_resource_database[collection_name].find_one({
        "_id": identifier,
    }) is None
    assert clean_resource_database.resource_identifiers.find_one({
        "_id": identifier,
    }) is not None


def test_pre_allocator_sku_and_batch_are_tombstoned_on_delete(
    client, clean_resource_database
):
    clean_resource_database.sku.insert_one({
        "_id": "SKU000060",
        "name": "Old SKU",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    clean_resource_database.batch.insert_one({
        "_id": "BAT000060",
        "sku_id": None,
        "name": "Old batch",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })

    assert client.delete("/api/sku/SKU60").status_code == 204
    assert client.delete("/api/batch/BAT60").status_code == 200
    assert post_sku(client, "old-sku-reuse", {"id": "SKU60"}).status_code == 409
    assert post_batch(client, "old-batch-reuse", {"id": "BAT60"}).status_code == 409
    assert clean_resource_database.resource_identifiers.find_one({
        "_id": "SKU000060",
    })
    assert clean_resource_database.resource_identifiers.find_one({
        "_id": "BAT000060",
    })


def test_concurrent_distinct_resource_commands_allocate_distinct_ids(
    clean_resource_database,
):
    repositories = (
        ResourceRepository(clean_resource_database),
        ResourceRepository(clean_resource_database),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda pair: pair[0].create(
                "SKU",
                {"name": pair[1]},
                idempotency_key=f"create-{pair[1]}",
            ),
            zip(repositories, ("alpha", "beta")),
        ))

    assert {result.state["id"] for result in results} == {
        "SKU000001",
        "SKU000002",
    }
    assert clean_resource_database.sku.count_documents({}) == 2
    assert clean_resource_database.resource_identifiers.count_documents({
        "prefix": "SKU",
    }) == 2


def test_upgrade_reconciles_all_stale_sources_upward_and_reserves_old_floors(
    client, clean_resource_database
):
    clean_resource_database.identifier_counters.insert_one({
        "_id": "SKU",
        "next_number": 4,
    })
    clean_resource_database.inventory_counters.insert_one({
        "_id": "SKU",
        "next_number": 7,
    })
    clean_resource_database.admin.insert_one({
        "_id": "SKU",
        "next": "SKU000009",
        "used": [2],
    })
    clean_resource_database.sku.insert_one({
        "_id": "SKU000012",
        "name": "Live legacy SKU",
    })
    clean_resource_database.resource_identifiers.insert_one({
        "_id": "SKU000015",
        "prefix": "SKU",
        "number": 15,
    })

    created = post_sku(client, "after-all-old-sources", {"name": "New"})
    reserved_gap = post_sku(
        client,
        "old-counter-gap",
        {"id": "SKU000008", "name": "Unsafe reuse"},
    )

    assert created.json["state"]["id"] == "SKU000016"
    assert reserved_gap.status_code == 409
    counter = clean_resource_database.identifier_counters.find_one({"_id": "SKU"})
    assert counter["next_number"] == 17
    assert counter["legacy_reserved_below"] == 9
    assert counter["managed_by"] == ALLOCATOR_MARKER
    assert clean_resource_database.inventory_counters.find_one({
        "_id": "SKU",
    })["next_number"] == 17
    assert clean_resource_database.admin.find_one({"_id": "SKU"})["next"] == (
        "SKU000017"
    )


def test_managed_allocator_uses_fast_path_after_one_migration(
    clean_resource_database, monkeypatch
):
    repository = ResourceRepository(clean_resource_database)
    assert repository.next_available_id("SKU") == "SKU000001"

    def fail_if_rescanned(*args, **kwargs):
        raise AssertionError("managed allocator performed a legacy O(N) scan")

    monkeypatch.setattr(repository.identifiers, "_known_numbers", fail_if_rescanned)
    assert repository.next_available_id("SKU") == "SKU000001"
    created = repository.create(
        "SKU",
        {"name": "Fast path"},
        idempotency_key="fast-path-create",
    )
    assert created.state["id"] == "SKU000001"


def test_seven_digit_legacy_next_is_terminal_and_malformed_claim_is_ignored(
    client, clean_resource_database
):
    clean_resource_database.admin.insert_one({
        "_id": "SKU",
        "next": "SKU1000000",
        "used": [],
    })
    clean_resource_database.resource_identifiers.insert_one({
        "_id": "malformed-legacy-claim",
        "prefix": "SKU",
        "number": "not-a-number",
    })

    preview = client.get("/api/next/sku")
    create = post_sku(client, "past-terminal", {"name": "Impossible"})

    assert preview.status_code == 409
    assert create.status_code == 409
    assert create.json["type"] == "identifier-space-exhausted"
    assert clean_resource_database.sku.count_documents({}) == 0


def test_explicit_zero_remains_valid_and_does_not_skip_generated_one(
    client, clean_resource_database
):
    zero = post_sku(client, "explicit-zero", {"id": "SKU0"})
    one = post_sku(client, "automatic-one")

    assert zero.status_code == 201
    assert zero.json["state"]["id"] == "SKU000000"
    assert one.status_code == 201
    assert one.json["state"]["id"] == "SKU000001"


def test_migration_repairs_malformed_claim_and_normalizes_admin_used(
    client, clean_resource_database
):
    clean_resource_database.admin.insert_one({
        "_id": "SKU",
        "next": "SKU000005",
        "used": None,
    })
    clean_resource_database.resource_identifiers.insert_one({
        "_id": "SKU000007",
        "prefix": "SKU",
        "number": "not-a-number",
    })

    created = post_sku(client, "after-malformed-state", {"name": "New"})

    assert created.status_code == 201
    assert created.json["state"]["id"] == "SKU000008"
    assert clean_resource_database.resource_identifiers.find_one({
        "_id": "SKU000007",
    })["number"] == 7
    admin = clean_resource_database.admin.find_one({"_id": "SKU"})
    assert admin["used"] == [7, 8]
    assert admin["next"] == "SKU000009"


@pytest.mark.parametrize("legacy_used", [7, "7", "SKU000007"])
def test_migration_preserves_recoverable_scalar_admin_used(
    client, clean_resource_database, legacy_used
):
    clean_resource_database.admin.insert_one({
        "_id": "SKU",
        "next": "SKU000001",
        "used": legacy_used,
    })

    created = post_sku(client, f"after-scalar-{legacy_used}", {"name": "New"})
    reuse = post_sku(
        client,
        f"reuse-scalar-{legacy_used}",
        {"id": "SKU7", "name": "Wrong"},
    )

    assert created.status_code == 201
    assert created.json["state"]["id"] == "SKU000008"
    assert reuse.status_code == 409
    admin = clean_resource_database.admin.find_one({"_id": "SKU"})
    assert admin["used"] == [7, 8]
    assert admin["next"] == "SKU000009"


def test_legacy_monotonic_floor_does_not_falsely_reserve_zero(
    client, clean_resource_database
):
    clean_resource_database.identifier_counters.insert_one({
        "_id": "SKU",
        "next_number": 20,
    })
    clean_resource_database.inventory_counters.insert_one({
        "_id": "SKU",
        "next_number": 30,
    })
    clean_resource_database.admin.insert_one({
        "_id": "SKU",
        "next": "SKU000040",
        "used": [],
    })

    zero = post_sku(client, "legacy-explicit-zero", {"id": "sku0"})
    generated = post_sku(client, "after-legacy-zero")

    assert zero.status_code == 201
    assert zero.json["state"]["id"] == "SKU000000"
    assert generated.json["state"]["id"] == "SKU000040"


def test_batch_exhaustion_rolls_back_quick_capture_sku_and_operation(
    client, clean_resource_database
):
    clean_resource_database.bin.insert_one({
        "_id": "BIN000001",
        "contents": {},
        "props": {},
    })
    clean_resource_database.identifier_counters.insert_one({
        "_id": "BAT",
        "next_number": 1_000_000,
    })

    response = client.post(
        "/api/intake",
        headers={"Idempotency-Key": "capture-at-batch-exhaustion"},
        json={
            "description": "Must roll back",
            "bin_id": "BIN000001",
            "quantity": 1,
        },
    )

    assert response.status_code == 409
    assert response.json["prefix"] == "BAT"
    assert clean_resource_database.sku.count_documents({}) == 0
    assert clean_resource_database.batch.count_documents({}) == 0
    assert clean_resource_database.inventory_operations.count_documents({}) == 0
    assert clean_resource_database.inventory_holdings.count_documents({}) == 0
    assert clean_resource_database.resource_identifiers.count_documents({
        "prefix": {"$in": ["SKU", "BAT"]},
    }) == 0


def test_batch_create_and_sku_delete_never_commit_a_dangling_reference(
    clean_resource_database,
):
    clean_resource_database.sku.insert_one({
        "_id": "SKU000001",
        "name": "Racing SKU",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    resource_repository = ResourceRepository(clean_resource_database)
    inventory_repository = InventoryRepository(clean_resource_database)
    barrier = Barrier(2)

    def create_batch():
        barrier.wait()
        try:
            return resource_repository.create(
                "BAT",
                {"sku_id": "SKU000001"},
                idempotency_key="racing-batch-create",
            )
        except MissingResourceReference as error:
            return error

    def delete_sku():
        barrier.wait()
        try:
            inventory_repository.delete_legacy_sku("SKU000001")
            return "deleted"
        except LedgerReferencedSku as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        create_future = executor.submit(create_batch)
        delete_future = executor.submit(delete_sku)
        create_result = create_future.result()
        delete_result = delete_future.result()

    sku_exists = clean_resource_database.sku.find_one({
        "_id": "SKU000001",
    }) is not None
    batch_exists = clean_resource_database.batch.find_one({
        "sku_id": "SKU000001",
    }) is not None
    assert (sku_exists, batch_exists) in {
        (True, True),
        (False, False),
    }
    if batch_exists:
        assert not isinstance(create_result, Exception)
        assert isinstance(delete_result, LedgerReferencedSku)
    else:
        assert isinstance(create_result, MissingResourceReference)
        assert delete_result == "deleted"
