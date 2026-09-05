"""An item's implicit root is scoped to its persisted identity, not its name."""

from copy import deepcopy

import pytest

from tests.database import get_test_database


@pytest.fixture
def resource_schema(client):
    database = get_test_database()
    definitions = {}
    for name, prefix in (("sku", "SKU"), ("batch", "BAT")):
        for number in (1, 2):
            database[name].replace_one(
                {"_id": f"{prefix}{number:06}"},
                {"_id": f"{prefix}{number:06}", "name": "Same editable name"},
                upsert=True,
            )
        definition = {
            "root_mixins": ["Description"],
            "mixins": {
                "Description": {"name": "Description", "fields": [
                    {"name": "description", "type": "text"},
                ]},
                f"{prefix}000001": {
                    "name": f"{prefix}000001",
                    "fields": [{"name": "jaw_count", "type": "number"}],
                    "children": [{"mixin": "ThreeJaw", "trigger": {
                        "field": "jaw_count", "op": "eq", "value": 3,
                    }}],
                },
                "ThreeJaw": {"name": "ThreeJaw", "fields": [
                    {"name": "mounting", "type": "text"},
                ]},
                f"{prefix}000003": {"name": f"{prefix}000003", "fields": [
                    {"name": "not_created_yet", "type": "text"},
                ]},
            },
            "intersections": [{"when": ["Description", f"{prefix}000001"],
                               "adds": [{"name": "source", "type": "text"}]}],
        }
        assert client.put(f"/api/schema/{name}", json=definition).status_code == 200
        definitions[name] = client.get(f"/api/schema/{name}").json
    return database, definitions


@pytest.mark.parametrize("name,prefix", [("sku", "SKU"), ("batch", "BAT")])
def test_persisted_identity_adds_ordinary_mixin_without_changing_roots(
    client, resource_schema, name, prefix,
):
    database, definitions = resource_schema
    before = deepcopy(database.schema.find_one({"_id": name}))
    response = client.post(f"/api/schema/{name}/evaluate", json={
        "resource_id": f"{prefix}000001",
        "field_values": {"jaw_count": 3},
    })
    assert response.status_code == 200
    assert response.json["active_mixins"] == ["Description", f"{prefix}000001", "ThreeJaw"]
    assert response.json["implicit_root_mixins"] == [f"{prefix}000001"]
    assert {f["name"] for f in response.json["available_fields"]} == {
        "description", "jaw_count", "mounting", "source",
    }
    assert database.schema.find_one({"_id": name}) == before
    assert client.get(f"/api/schema/{name}").json == definitions[name]

    other = client.post(f"/api/schema/{name}/evaluate", json={
        "resource_id": f"{prefix}000002", "field_values": {"jaw_count": 3},
    })
    assert other.json["active_mixins"] == ["Description"]
    assert other.json["implicit_root_mixins"] == []


@pytest.mark.parametrize("name,prefix", [("sku", "SKU"), ("batch", "BAT")])
def test_new_forms_read_all_roots_but_do_not_predict_identity(client, resource_schema, name, prefix):
    response = client.post(f"/api/schema/{name}/evaluate", json={
        "use_schema_roots": True, "field_values": {},
    })
    assert response.json["active_mixins"] == ["Description"]
    assert response.json["implicit_root_mixins"] == []
    absent = client.post(f"/api/schema/{name}/evaluate", json={
        "resource_id": f"{prefix}000003", "field_values": {},
    })
    assert absent.status_code == 404


@pytest.mark.parametrize("resource_id", ["BAT000001", "SKU1", "sku000001", 1, {}, "SKU000001x"])
def test_wrong_schema_and_noncanonical_ids_rejected(client, resource_schema, resource_id):
    assert client.post("/api/schema/sku/evaluate", json={
        "resource_id": resource_id, "field_values": {},
    }).status_code == 400


def test_admin_preview_can_still_explicitly_select_mixins(client, resource_schema):
    response = client.post("/api/schema/sku/evaluate", json={
        "active_mixins": ["SKU000001"], "field_values": {},
    })
    assert response.json["active_mixins"] == ["SKU000001"]
    assert response.json["implicit_root_mixins"] == []


def test_removing_mixin_does_not_remove_saved_values(client, resource_schema):
    database, definitions = resource_schema
    database.sku.update_one({"_id": "SKU000001"}, {"$set": {"props": {"jaw_count": 3}}})
    definition = deepcopy(definitions["sku"])
    del definition["mixins"]["SKU000001"]
    assert client.put("/api/schema/sku", json=definition).status_code == 200
    response = client.post("/api/schema/sku/evaluate", json={"resource_id": "SKU000001"})
    assert response.json["active_mixins"] == ["Description"]
    assert database.sku.find_one({"_id": "SKU000001"})["props"] == {"jaw_count": 3}
