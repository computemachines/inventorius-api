"""Contract coverage for actor-attributed legacy mutation receipts."""

from io import BytesIO
import importlib

import pytest

from tests.database import get_test_database


ACTOR = {"actor_id": "owner", "actor_type": "owner"}
files_module = importlib.import_module("inventorius.files")


@pytest.fixture(autouse=True)
def clean_mutation_receipt_database():
    database = get_test_database()
    for name in (
        "admin", "bin", "sku", "batch", "files", "schema",
        "process_definition", "process_run", "mutation_receipts",
        "resource_commands", "resource_identifiers", "identifier_counters",
    ):
        database[name].delete_many({})
    yield database


def _receipts(database, *kinds):
    return list(database.mutation_receipts.find({"kind": {"$in": kinds}}))


def test_catalog_update_and_delete_receipts_include_actor(client, clean_mutation_receipt_database):
    created = client.post(
        "/api/skus", headers={"Idempotency-Key": "receipt-sku"}, json={"name": "Tape"}
    )
    sku_id = created.json["state"]["id"]
    assert client.patch(f"/api/sku/{sku_id}", json={"name": "Wide tape"}).status_code == 200
    assert client.delete(f"/api/sku/{sku_id}").status_code == 204

    receipts = _receipts(clean_mutation_receipt_database, "catalog.sku.update", "catalog.sku.delete")
    assert {receipt["kind"] for receipt in receipts} == {"catalog.sku.update", "catalog.sku.delete"}
    assert all(receipt["target"] == sku_id and receipt["actor"] == ACTOR for receipt in receipts)


def test_file_receipts_include_actor(client, clean_mutation_receipt_database, monkeypatch, tmp_path):
    monkeypatch.setattr(files_module, "UPLOADS_PATH", str(tmp_path))
    uploaded = client.post(
        "/api/files",
        data={"file": (BytesIO(b"%PDF-1.4\nminimal"), "note.pdf")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json["state"]["id"]
    assert client.delete(f"/api/files/{file_id}").status_code == 200

    receipts = _receipts(clean_mutation_receipt_database, "file.upload", "file.delete")
    assert {receipt["kind"] for receipt in receipts} == {"file.upload", "file.delete"}
    assert all(receipt["target"] == file_id and receipt["actor"] == ACTOR for receipt in receipts)


def test_schema_administration_and_seed_receipts_include_actor(client, clean_mutation_receipt_database):
    schema = {"root_mixins": [], "mixins": {}, "intersections": []}
    assert client.put("/api/schema/test", json=schema).status_code == 200
    assert client.delete("/api/schema/test").status_code == 200
    assert client.post("/api/schema/seed").status_code == 200

    receipts = _receipts(clean_mutation_receipt_database, "schema.save", "schema.delete", "schema.seed")
    assert {receipt["kind"] for receipt in receipts} == {"schema.save", "schema.delete", "schema.seed"}
    assert all(receipt["actor"] == ACTOR for receipt in receipts)


def test_process_mutation_receipts_include_actor(client, clean_mutation_receipt_database):
    clean_mutation_receipt_database.sku.insert_one({
        "_id": "SKU000001", "name": "Glue", "owned_codes": [],
        "associated_codes": [], "props": {},
    })
    payload = {
        "name": "Repack", "kind": "repackaging", "description": "",
        "inputs": [{"role": "in", "sku_id": "SKU000001", "quantity": 1, "unit": "each"}],
        "outputs": [{"role": "out", "sku_id": "SKU000001", "quantity": 1, "unit": "each"}],
        "instructions": [],
    }
    assert client.post("/api/process-definitions", json=payload).status_code == 201
    assert client.patch("/api/process-definition/PRC000001", json={"name": "Repack v2"}).status_code == 200
    assert client.delete("/api/process-definition/PRC000001").status_code == 200

    receipts = _receipts(
        clean_mutation_receipt_database,
        "process-definition.create", "process-definition.update", "process-definition.delete",
    )
    assert {receipt["kind"] for receipt in receipts} == {
        "process-definition.create", "process-definition.update", "process-definition.delete",
    }
    assert all(receipt["target"] == "PRC000001" and receipt["actor"] == ACTOR for receipt in receipts)
