import pytest

from tests.database import get_test_database


@pytest.fixture(autouse=True)
def batch_document():
    database = get_test_database()
    database.batch.delete_many({})
    database.batch.insert_one({
        "_id": "BAT000001",
        "name": "Typed affordance test",
        "owned_codes": [],
        "associated_codes": [],
        "props": {},
    })
    yield
    database.batch.delete_many({})


def by_rel(response):
    return {operation["rel"]: operation for operation in response.json["operations"]}


def test_anonymous_batch_advertises_only_typed_locations_read(anonymous_client):
    response = anonymous_client.get("/api/batch/BAT000001")

    assert response.status_code == 200
    assert by_rel(response) == {
        "bins": {
            "rel": "bins",
            "method": "GET",
            "href": "/api/batch/BAT000001/bins",
            "kind": "catalog.batch.locations.read",
            "request_schema": None,
            "response_schema": {
                "name": "inventorius.batch-locations", "version": 1
            },
            "idempotency": {"mode": "not-applicable"},
        }
    }


def test_missing_batch_create_affordance_is_also_caller_truthful(
    client, anonymous_client
):
    anonymous = anonymous_client.get("/api/batch/BAT999999")
    owner = client.get("/api/batch/BAT999999")

    assert anonymous.status_code == 404
    assert "operations" not in anonymous.json
    assert owner.status_code == 404
    assert by_rel(owner)["create"]["kind"] == "catalog.batch.create"


def test_owner_batch_advertises_typed_update_delete_and_locations(client):
    operations = by_rel(client.get("/api/batch/BAT000001"))

    assert set(operations) == {"update", "delete", "bins"}
    assert operations["update"] == {
        "rel": "update",
        "method": "PATCH",
        "href": "/api/batch/BAT000001",
        "Expects-a": "Batch patch",
        "kind": "catalog.batch.update",
        "request_schema": {"name": "inventorius.batch-patch", "version": 1},
        "response_schema": {
            "name": "inventorius.operation-status", "version": 1
        },
        "idempotency": {"mode": "not-supported"},
    }
    assert operations["delete"] == {
        "rel": "delete",
        "method": "DELETE",
        "href": "/api/batch/BAT000001",
        "kind": "catalog.batch.delete",
        "request_schema": None,
        "response_schema": {
            "name": "inventorius.operation-status", "version": 1
        },
        "idempotency": {"mode": "not-supported"},
    }
    assert operations["bins"]["idempotency"] == {"mode": "not-applicable"}


def test_batch_update_response_matches_advertised_operation_status(client):
    response = client.patch(
        "/api/batch/BAT000001",
        json={"id": "BAT000001", "name": "Updated name"},
    )

    assert response.status_code == 200
    assert response.json == {
        "Id": "/api/batch/BAT000001",
        "status": "batch updated",
    }


def test_application_root_advertises_typed_batch_creation_only_to_owner(
    client, anonymous_client
):
    assert anonymous_client.get("/api/").json["operations"] == []

    operations = by_rel(client.get("/api/"))
    create = operations["create-batch"]
    assert create == {
        "rel": "create-batch",
        "method": "POST",
        "href": "/api/batches",
        "Expects-a": "Batch patch",
        "kind": "catalog.batch.create",
        "request_schema": {"name": "inventorius.batch-create", "version": 1},
        "response_schema": {
            "name": "inventorius.batch-creation-result", "version": 1
        },
        "idempotency": {
            "mode": "required",
            "key": {
                "in": "header",
                "name": "Idempotency-Key",
                "max_length": 200,
            },
            "scope": "resource-creation",
            "replay": "return-committed-result",
            "mismatch": "conflict",
        },
    }


def test_batch_endpoint_denies_mutation_even_without_advertisement(anonymous_client):
    patch = anonymous_client.patch("/api/batch/BAT000001", json={"id": "BAT000001"})
    delete = anonymous_client.delete("/api/batch/BAT000001")
    create = anonymous_client.post(
        "/api/batches", headers={"Idempotency-Key": "denied"}, json={}
    )

    assert patch.status_code == 401
    assert delete.status_code == 401
    assert create.status_code == 401
