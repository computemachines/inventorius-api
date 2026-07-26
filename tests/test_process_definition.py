"""API contract tests for visible, revisioned manufacturing definitions."""

import pytest

from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_process_database():
    database = get_test_database()
    for collection in (
        database.admin,
        database.bin,
        database.process_definition,
        database.process_run,
        database.sku,
    ):
        collection.delete_many({})
    yield database
    for collection in (
        database.admin,
        database.bin,
        database.process_definition,
        database.process_run,
        database.sku,
    ):
        collection.delete_many({})


def _definition(**overrides):
    definition = {
        "name": "Open glue-stick case",
        "kind": "repackaging",
        "description": "Break a sealed case into its contained boxes.",
        "inputs": [{
            "role": "Sealed case",
            "sku_id": "SKU000001",
            "quantity": 1,
            "unit": "case",
        }],
        "outputs": [{
            "role": "Boxes",
            "sku_id": "SKU000001",
            "quantity": 10,
            "unit": "box",
        }],
        "instructions": ["Open the case.", "Count the boxes."],
    }
    definition.update(overrides)
    return definition


def _insert_sku(database):
    database.sku.insert_one({
        "_id": "SKU000001",
        "name": "Glue sticks",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })


def test_create_list_and_get_process_definition(client, clean_process_database):
    _insert_sku(clean_process_database)

    created = client.post("/api/process-definitions", json=_definition())

    assert created.status_code == 201
    assert created.json == {
        "Id": "/api/process-definition/PRC000001",
        "status": "process definition created",
    }

    listed = client.get("/api/process-definitions")
    assert listed.status_code == 200
    assert len(listed.json["state"]) == 1
    summary = listed.json["state"][0]
    assert summary["id"] == "PRC000001"
    assert summary["name"] == "Open glue-stick case"
    assert summary["revision"] == 1
    assert summary["is_current"] is True

    fetched = client.get("/api/process-definition/PRC1")
    assert fetched.status_code == 200
    assert fetched.json["state"]["id"] == "PRC000001"
    assert fetched.json["state"]["inputs"][0]["unit"] == "case"
    assert {operation["rel"] for operation in fetched.json["operations"]} == {
        "update",
        "delete",
        "revisions",
    }


def test_patch_appends_revision_and_preserves_old_definition(
    client,
    clean_process_database,
):
    _insert_sku(clean_process_database)
    client.post("/api/process-definitions", json=_definition())

    updated = client.patch(
        "/api/process-definition/PRC000001",
        json={
            "name": "Open case into boxes",
            "outputs": [{
                "role": "Boxes",
                "sku_id": "SKU1",
                "quantity": 12,
                "unit": "box",
            }],
        },
    )

    assert updated.status_code == 200
    current = client.get("/api/process-definition/PRC000001").json["state"]
    assert current["revision"] == 2
    assert current["name"] == "Open case into boxes"
    assert current["outputs"][0]["sku_id"] == "SKU000001"
    assert current["outputs"][0]["quantity"] == 12

    original = client.get(
        "/api/process-definition/PRC000001",
        query_string={"revision": 1},
    )
    assert original.status_code == 200
    assert original.json["state"]["name"] == "Open glue-stick case"
    assert original.json["state"]["outputs"][0]["quantity"] == 10
    assert original.json["state"]["is_current"] is False
    assert {operation["rel"] for operation in original.json["operations"]} == {
        "revisions"
    }

    revisions = client.get(
        "/api/process-definition/PRC000001/revisions"
    ).json["state"]
    assert [revision["revision"] for revision in revisions] == [2, 1]


@pytest.mark.parametrize(
    "payload,field",
    [
        (_definition(inputs=[]), "inputs"),
        (_definition(kind="mystery"), "kind"),
        (_definition(inputs=[{"role": "Case", "quantity": 0, "unit": "case"}]), "inputs"),
        (_definition(inputs=[{"role": "Case", "sku_id": "SKU999999", "unit": "case"}]), "inputs"),
    ],
)
def test_create_rejects_invalid_definitions(
    client,
    clean_process_database,
    payload,
    field,
):
    _insert_sku(clean_process_database)

    response = client.post("/api/process-definitions", json=payload)

    assert response.status_code == 400
    assert response.json["type"] == "validation-error"
    assert response.json["invalid-params"][0]["name"] == field
    assert clean_process_database.process_definition.count_documents({}) == 0


def test_delete_unused_definition_but_not_definition_used_by_run(
    client,
    clean_process_database,
):
    _insert_sku(clean_process_database)
    client.post("/api/process-definitions", json=_definition())

    clean_process_database.process_run.insert_one({
        "_id": "RUN000001",
        "process_definition_id": "PRC000001",
        "process_definition_revision": 1,
    })
    blocked = client.delete("/api/process-definition/PRC000001")
    assert blocked.status_code == 403
    assert blocked.json["type"] == "resource-in-use"

    clean_process_database.process_run.delete_many({})
    deleted = client.delete("/api/process-definition/PRC000001")
    assert deleted.status_code == 200
    assert deleted.json["status"] == "process definition deleted"
    assert clean_process_database.process_definition.count_documents({}) == 0


def test_sku_referenced_by_process_definition_cannot_be_deleted(
    client,
    clean_process_database,
):
    _insert_sku(clean_process_database)
    client.post("/api/process-definitions", json=_definition())

    response = client.delete("/api/sku/SKU000001")

    assert response.status_code == 403
    assert response.json["type"] == "resource-in-use"
    assert clean_process_database.sku.count_documents({}) == 1
