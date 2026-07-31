"""API and storage contracts for immutable dynamic-schema revisions."""

from copy import deepcopy

import pytest

from inventorius.schema.repository import SchemaEditConflict, SchemaRepository
from tests.database import get_test_database


ACTOR = {"actor_id": "owner", "actor_type": "owner"}


def schema_definition(*, field_name: str = "name"):
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
def clean_schema_revision_database():
    database = get_test_database()
    for name in ("schema", "schema_revision", "mutation_receipts"):
        database[name].delete_many({})
    yield database


def test_create_and_identical_put_publish_only_one_revision(
    client,
    clean_schema_revision_database,
):
    definition = schema_definition()

    assert client.put("/api/schema/component", json=definition).status_code == 200
    assert client.put("/api/schema/component", json=definition).status_code == 200

    head = clean_schema_revision_database.schema.find_one({
        "_id": "component"
    })
    assert head == {
        "_id": "component",
        "head_revision": 1,
        "active_revision": 1,
        "definition": definition,
    }
    revision = clean_schema_revision_database.schema_revision.find_one({
        "_id": {"schema_name": "component", "revision": 1}
    })
    assert revision["parent_revision"] is None
    assert revision["actor"] == ACTOR
    assert revision["published_at"] is not None
    assert revision["compatibility"] == "unspecified"
    assert revision["definition"] == definition
    assert clean_schema_revision_database.mutation_receipts.count_documents({
        "kind": "schema.save",
        "target": "component",
    }) == 1
    assert client.get("/api/schema/component").json == definition


def test_changed_put_preserves_history_and_historical_evaluation(
    client,
    clean_schema_revision_database,
):
    original = schema_definition(field_name="old_field")
    changed = schema_definition(field_name="new_field")
    assert client.put("/api/schema/component", json=original).status_code == 200
    assert client.put("/api/schema/component", json=changed).status_code == 200

    assert client.get("/api/schema/component").json == changed
    assert client.get("/api/schema/component?revision=1").json == original
    assert client.get("/api/schema/component?revision=2").json == changed
    old_evaluation = client.post(
        "/api/schema/component/evaluate?revision=1",
        json={"active_mixins": ["Base"], "field_values": {}},
    )
    current_evaluation = client.post(
        "/api/schema/component/evaluate",
        json={"active_mixins": ["Base"], "field_values": {}},
    )
    assert old_evaluation.status_code == 200
    assert [field["name"] for field in old_evaluation.json["available_fields"]] == [
        "old_field"
    ]
    assert [
        field["name"] for field in current_evaluation.json["available_fields"]
    ] == ["new_field"]

    revisions = list(
        clean_schema_revision_database.schema_revision.find({
            "schema_name": "component"
        }).sort("revision")
    )
    assert [revision["revision"] for revision in revisions] == [1, 2]
    assert revisions[1]["parent_revision"] == 1
    assert revisions[0]["definition"] == original


def test_mixin_and_root_mutations_each_publish_from_the_observed_head(
    client,
    clean_schema_revision_database,
):
    original = schema_definition()
    assert client.put("/api/schema/component", json=original).status_code == 200
    mixin = {
        "name": "ignored-url-name-wins",
        "fields": [{"name": "detail", "type": "text"}],
        "children": [],
    }

    assert client.put(
        "/api/schema/component/mixin/Extra",
        json=mixin,
    ).status_code == 200
    assert client.put(
        "/api/schema/component/root/Extra"
    ).status_code == 200
    assert client.delete(
        "/api/schema/component/root/Extra"
    ).status_code == 200
    assert client.delete(
        "/api/schema/component/mixin/Extra"
    ).status_code == 200

    head = clean_schema_revision_database.schema.find_one({
        "_id": "component"
    })
    assert head["head_revision"] == 5
    assert clean_schema_revision_database.schema_revision.count_documents({
        "schema_name": "component"
    }) == 5
    assert "Extra" not in client.get("/api/schema/component?revision=1").json[
        "mixins"
    ]
    revision_two = client.get("/api/schema/component?revision=2").json
    assert revision_two["mixins"]["Extra"]["name"] == "Extra"
    assert "Extra" not in revision_two["root_mixins"]
    assert "Extra" in client.get("/api/schema/component?revision=3").json[
        "root_mixins"
    ]
    assert "Extra" not in client.get("/api/schema/component").json["mixins"]


def test_delete_deactivates_without_erasing_history_and_put_reactivates(
    client,
    clean_schema_revision_database,
):
    definition = schema_definition()
    client.put("/api/schema/component", json=definition)

    response = client.delete("/api/schema/component")

    assert response.status_code == 200
    assert client.get("/api/schema/component").status_code == 404
    assert client.get("/api/schema/component?revision=1").json == definition
    assert "component" not in client.get("/api/schema/list").json["schemas"]
    head = clean_schema_revision_database.schema.find_one({
        "_id": "component"
    })
    assert head["head_revision"] == 1
    assert head["active_revision"] is None
    assert clean_schema_revision_database.schema_revision.count_documents({
        "schema_name": "component"
    }) == 1

    assert client.put("/api/schema/component", json=definition).status_code == 200
    assert client.get("/api/schema/component").json == definition
    assert clean_schema_revision_database.schema_revision.count_documents({
        "schema_name": "component"
    }) == 1


def test_first_changed_legacy_publication_captures_exact_unknown_baseline(
    client,
    clean_schema_revision_database,
):
    original = schema_definition(field_name="legacy")
    legacy_document = {
        "_id": "component",
        **deepcopy(original),
        "legacy_note": "preserve this exact source document",
    }
    clean_schema_revision_database.schema.insert_one(legacy_document)

    assert client.get("/api/schema/component").json == original
    changed = schema_definition(field_name="published")
    assert client.put("/api/schema/component", json=changed).status_code == 200

    baseline = clean_schema_revision_database.schema_revision.find_one({
        "_id": {"schema_name": "component", "revision": 1}
    })
    publication = clean_schema_revision_database.schema_revision.find_one({
        "_id": {"schema_name": "component", "revision": 2}
    })
    assert baseline["definition"] == {
        key: value for key, value in legacy_document.items() if key != "_id"
    }
    assert baseline["actor"] is None
    assert baseline["published_at"] is None
    assert baseline["compatibility"] == "unspecified"
    assert publication["definition"] == changed
    assert publication["parent_revision"] == 1
    assert publication["actor"] == ACTOR
    assert publication["published_at"] is not None
    assert client.get("/api/schema/component?revision=1").json == original


def test_deleting_a_legacy_schema_captures_baseline_before_deactivation(
    client,
    clean_schema_revision_database,
):
    original = schema_definition(field_name="legacy")
    clean_schema_revision_database.schema.insert_one({
        "_id": "component",
        **deepcopy(original),
    })

    assert client.delete("/api/schema/component").status_code == 200

    assert client.get("/api/schema/component").status_code == 404
    assert client.get("/api/schema/component?revision=1").json == original
    baseline = clean_schema_revision_database.schema_revision.find_one({
        "_id": {"schema_name": "component", "revision": 1}
    })
    assert baseline["actor"] is None
    assert baseline["published_at"] is None


def test_stale_schema_head_is_rejected_by_compare_and_swap(
    clean_schema_revision_database,
):
    repository = SchemaRepository(clean_schema_revision_database)
    missing = repository.head("component")
    repository.publish(
        "component",
        schema_definition(field_name="winner"),
        actor=ACTOR,
        expected=missing,
    )

    with pytest.raises(SchemaEditConflict):
        repository.publish(
            "component",
            schema_definition(field_name="stale"),
            actor=ACTOR,
            expected=missing,
        )

    assert repository.definition("component") == schema_definition(
        field_name="winner"
    )


@pytest.mark.parametrize("revision", ["nope", "0", "-1"])
def test_historical_read_rejects_invalid_revision(client, revision):
    response = client.get(f"/api/schema/component?revision={revision}")

    assert response.status_code == 400
