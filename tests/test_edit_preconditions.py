"""HTTP preconditions for bounded catalog and schema edits."""

from copy import deepcopy

import pytest
from pymongo.collection import Collection

from inventorius.schema import routes as schema_routes
from inventorius.schema.repository import SchemaRepository
from tests.database import get_test_database


ACTOR = {"actor_id": "concurrent-test", "actor_type": "test"}


def schema_definition(field_name="name"):
    return {
        "root_mixins": ["Base"],
        "mixins": {
            "Base": {
                "name": "Base",
                "fields": [{"name": field_name, "type": "text"}],
                "children": [],
            }
        },
        "intersections": [],
    }


@pytest.fixture(autouse=True)
def clean_edit_precondition_database():
    database = get_test_database()
    for name in (
        "sku",
        "batch",
        "schema",
        "schema_revision",
        "mutation_receipts",
    ):
        database[name].delete_many({})
    yield database
    for name in (
        "sku",
        "batch",
        "schema",
        "schema_revision",
        "mutation_receipts",
    ):
        database[name].delete_many({})


@pytest.mark.parametrize(
    ("path", "collection", "document"),
    [
        (
            "/api/sku/SKU000001",
            "sku",
            {
                "_id": "SKU000001",
                "name": "Chuck",
                "owned_codes": ["owned-sku"],
                "associated_codes": ["seen-sku"],
                "props": {"name": "Chuck", "description": "Before"},
            },
        ),
        (
            "/api/batch/BAT000001",
            "batch",
            {
                "_id": "BAT000001",
                "sku_id": "SKU000001",
                "name": "First lot",
                "owned_codes": ["owned-batch"],
                "associated_codes": ["seen-batch"],
                "props": {"supplier": "Before"},
            },
        ),
    ],
)
def test_catalog_get_advertises_changing_etag(
    client,
    clean_edit_precondition_database,
    path,
    collection,
    document,
):
    database = clean_edit_precondition_database
    database[collection].insert_one(deepcopy(document))

    first = client.get(path)
    assert first.status_code == 200
    assert first.headers["Inventory-Edit-Preconditions"] == "etag-v1"
    assert first.headers["ETag"].startswith('"inventory-etag-v1-')

    database[collection].update_one(
        {"_id": document["_id"]}, {"$set": {"props.changed": True}}
    )
    assert client.get(path).headers["ETag"] != first.headers["ETag"]


def test_sku_patch_accepts_current_tag_and_remains_compatible_without_one(
    client,
    clean_edit_precondition_database,
):
    database = clean_edit_precondition_database
    database.sku.insert_one({
        "_id": "SKU000001",
        "name": "Original",
        "props": {"name": "Original", "kept": "yes"},
    })
    etag = client.get("/api/sku/SKU000001").headers["ETag"]

    guarded = client.patch(
        "/api/sku/SKU000001",
        headers={"If-Match": etag},
        json={
            "id": "SKU000001",
            "props": {"name": "Guarded", "kept": "yes"},
        },
    )
    compatible = client.patch(
        "/api/sku/SKU000001",
        json={"id": "SKU000001", "associated_codes": ["legacy-client"]},
    )

    assert guarded.status_code == 200
    assert compatible.status_code == 200
    saved = database.sku.find_one({"_id": "SKU000001"})
    assert saved["name"] == "Guarded"
    assert saved["props"] == {"name": "Guarded", "kept": "yes"}
    assert saved["associated_codes"] == ["legacy-client"]


def test_stale_sku_patch_is_rejected_without_overwriting_current_state(
    client,
    clean_edit_precondition_database,
):
    database = clean_edit_precondition_database
    database.sku.insert_one({
        "_id": "SKU000001",
        "name": "Observed",
        "props": {"name": "Observed"},
    })
    stale = client.get("/api/sku/SKU000001").headers["ETag"]
    database.sku.update_one(
        {"_id": "SKU000001"},
        {"$set": {"name": "Winner", "props": {"name": "Winner"}}},
    )

    response = client.patch(
        "/api/sku/SKU000001",
        headers={"If-Match": stale},
        json={"id": "SKU000001", "props": {"name": "Stale"}},
    )

    assert response.status_code == 412
    assert response.json["type"] == "edit-precondition-failed"
    assert database.sku.find_one({"_id": "SKU000001"})["name"] == "Winner"


def test_sku_precondition_is_rechecked_atomically_with_update(
    client,
    clean_edit_precondition_database,
    monkeypatch,
):
    database = clean_edit_precondition_database
    database.sku.insert_one({
        "_id": "SKU000001",
        "name": "Observed",
        "props": {"name": "Observed"},
    })
    etag = client.get("/api/sku/SKU000001").headers["ETag"]
    original_update_one = Collection.update_one
    injected = False

    def update_one_with_concurrent_winner(collection, selector, update, *args, **kwargs):
        nonlocal injected
        if collection.name == "sku" and "$and" in selector and not injected:
            injected = True
            original_update_one(
                collection,
                {"_id": "SKU000001"},
                {"$set": {"name": "Winner", "props": {"name": "Winner"}}},
            )
        return original_update_one(collection, selector, update, *args, **kwargs)

    monkeypatch.setattr(Collection, "update_one", update_one_with_concurrent_winner)
    response = client.patch(
        "/api/sku/SKU000001",
        headers={"If-Match": etag},
        json={"id": "SKU000001", "props": {"name": "Stale"}},
    )

    assert injected
    assert response.status_code == 412
    assert database.sku.find_one({"_id": "SKU000001"})["name"] == "Winner"


def test_batch_patch_applies_all_selected_changes_in_one_guarded_write(
    client,
    clean_edit_precondition_database,
    monkeypatch,
):
    database = clean_edit_precondition_database
    database.sku.insert_many([{"_id": "SKU000001"}, {"_id": "SKU000002"}])
    database.batch.insert_one({
        "_id": "BAT000001",
        "sku_id": "SKU000001",
        "name": "Before",
        "owned_codes": ["old-owned"],
        "associated_codes": ["old-seen"],
        "props": {"kept": "before"},
    })
    etag = client.get("/api/batch/BAT000001").headers["ETag"]
    original_update_one = Collection.update_one
    batch_updates = 0

    def counted_update_one(collection, selector, update, *args, **kwargs):
        nonlocal batch_updates
        if collection.name == "batch":
            batch_updates += 1
        return original_update_one(collection, selector, update, *args, **kwargs)

    monkeypatch.setattr(Collection, "update_one", counted_update_one)
    response = client.patch(
        "/api/batch/BAT000001",
        headers={"If-Match": etag},
        json={
            "id": "BAT000001",
            "sku_id": "SKU000001",
            "name": "After",
            "owned_codes": ["new-owned"],
            "associated_codes": ["new-seen"],
            "props": {"kept": "after"},
        },
    )

    assert response.status_code == 200
    assert batch_updates == 1
    saved = database.batch.find_one({"_id": "BAT000001"})
    assert saved["sku_id"] == "SKU000001"
    assert saved["name"] == "After"
    assert saved["owned_codes"] == ["new-owned"]
    assert saved["associated_codes"] == ["new-seen"]
    assert saved["props"]["kept"] == "after"


def test_missing_catalog_resources_are_not_created_by_guarded_patch(client):
    response = client.patch(
        "/api/batch/BAT999999",
        headers={"If-Match": '"inventory-etag-v1-missing"'},
        json={"id": "BAT999999", "props": {"unexpected": True}},
    )

    assert response.status_code == 404
    assert get_test_database().batch.find_one({"_id": "BAT999999"}) is None


def test_schema_get_and_put_support_optional_etag_preconditions(
    client,
    clean_edit_precondition_database,
):
    original = schema_definition("original")
    changed = schema_definition("changed")
    assert client.put("/api/schema/sku", json=original).status_code == 200
    observed = client.get("/api/schema/sku")

    assert observed.headers["Inventory-Edit-Preconditions"] == "etag-v1"
    assert client.put(
        "/api/schema/sku",
        headers={"If-Match": observed.headers["ETag"]},
        json=changed,
    ).status_code == 200
    assert client.get("/api/schema/sku").json == changed

    # Existing website clients remain compatible when they omit If-Match.
    assert client.put("/api/schema/sku", json=original).status_code == 200
    assert client.get("/api/schema/sku").json == original


def test_stale_schema_tag_is_rejected_before_publication(
    client,
    clean_edit_precondition_database,
):
    original = schema_definition("original")
    winner = schema_definition("winner")
    stale = schema_definition("stale")
    client.put("/api/schema/batch", json=original)
    etag = client.get("/api/schema/batch").headers["ETag"]
    client.put("/api/schema/batch", json=winner)

    response = client.put(
        "/api/schema/batch", headers={"If-Match": etag}, json=stale
    )

    assert response.status_code == 412
    assert client.get("/api/schema/batch").json == winner


def test_schema_repository_conflict_maps_to_412_for_conditional_put(
    client,
    clean_edit_precondition_database,
    monkeypatch,
):
    database = clean_edit_precondition_database
    original = schema_definition("original")
    winner = schema_definition("winner")
    stale = schema_definition("stale")
    client.put("/api/schema/sku", json=original)
    etag = client.get("/api/schema/sku").headers["ETag"]
    real_save = schema_routes._save_schema
    injected = False

    def save_after_concurrent_publication(name, schema, *, expected):
        nonlocal injected
        if not injected:
            injected = True
            repository = SchemaRepository(database)
            repository.publish(
                name,
                winner,
                actor=ACTOR,
                expected=repository.head(name),
            )
        return real_save(name, schema, expected=expected)

    monkeypatch.setattr(schema_routes, "_save_schema", save_after_concurrent_publication)
    response = client.put(
        "/api/schema/sku", headers={"If-Match": etag}, json=stale
    )

    assert injected
    assert response.status_code == 412
    assert SchemaRepository(database).definition("sku") == winner
