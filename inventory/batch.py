from flask import Blueprint, request, Response, url_for, after_this_request
from voluptuous.error import MultipleInvalid
from inventory.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import admin_increment_code, check_code_list
from inventory.validation import new_batch_schema
import inventory.util_error_responses as problem
import inventory.util_success_responses as success

from pymongo import TEXT

import json

batch = Blueprint("batch", __name__)


@batch.route("/api/batches", methods=['POST'])
def batches_post():
    @ after_this_request
    def no_cache(resp):
        resp.headers.add("Cache-Control", "no-cache")
        return resp

    try:
        json = new_batch_schema(request.json)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    batch = Batch.from_json(json)

    existing_batch = db.batch.find_one({"_id": batch.id})
    if existing_batch:
        return problem.duplicate_resource_response("id")
  
    if batch.sku_id:
        existing_sku = db.sku.find_one({"_id": batch.sku_id})
        if not existing_sku:
            return problem.invalid_params_response(problem.missing_resource_param_error("sku_id", "must be an existing sku id"))
       

    batch = Batch.from_json({
        "id": json["id"],
        "sku_id": json["id"],
        "name": request.json.get("name", None),
        "owned_codes": request.json.get("owned_codes", None),
        "associated_codes": request.json.get("associated_codes", None),
        "props": request.json.get("props", None)
    })

    admin_increment_code("BAT", batch.id)
    db.batch.insert_one(batch.to_mongodb_doc())

    # Add text index if not yet created
    # TODO: This should probably be turned into a global flag
    if "name_text" not in db.batch.index_information().keys():
        db.sku.create_index([("name", TEXT)])

    return success.batch_created_response(batch.id)

@batch.route("/api/batch/<id>", methods=["GET"])
def batch_get(id):
    resp = Response()
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))

    if not existing:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "This batch does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an existing batch id"
            }]
        })
        return resp
    else:
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps({
            "Id": url_for("batch.batch_get", id=id),
            "state": json.loads(existing.to_json()),
            "operations": [{
                "rel": "update",
                "method": "PATCH",
                "href": url_for("batch.batch_patch", id=id),
                "Expects-a": "Batch patch"
            }, {
                "rel": "delete",
                "method": "DELETE",
                "href": url_for("batch.batch_delete", id=id),
            }, {
                "rel": "bins",
                "method": "GET",
                "href": url_for("batch.batch_bins_get", id=id),
            }]
        })
        return resp


@batch.route("/api/batch/<id>", methods=["PATCH"])
def batch_patch(id):
    patch = request.json
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    resp = Response()
    resp.headers.add("Cache-Control", "no-cache")

    if not existing:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "Can not update nonexisting batch.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an existing batch id"
            }]
        })
        return resp

    if "sku_id" in patch.keys() and patch["sku_id"]:
        existing_sku = db.sku.find_one({"_id": patch['sku_id']})
        if not existing_sku:
            resp.status_code = 409
            resp.mimetype = "application/problem+json"
            resp.data = json.dumps({
                "type": "missing-resource",
                "title": "Cannot create a batch for non existing sku.",
                "invalid-params": [{
                    "name": "sku_id",
                    "reason": "must be an existing sku id"
                }]
            })
            return resp

    if existing.sku_id and "sku_id" in patch.keys() and patch["sku_id"] != existing.sku_id:
        resp.status_code = 409
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "dangerous-operation",
            "title": "Can not change the sku of a batch once set.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be a batch without sku_id set"
            }]
        })
        return resp

    if "props" in patch.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"props": patch['props']}})
    if "name" in patch.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"name": patch['name']}})

    if "sku_id" in patch.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"sku_id": patch['sku_id']}})

    if "owned_codes" in patch.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"owned_codes": patch['owned_codes']}})
    if "associated_codes" in patch.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"associated_codes": patch['associated_codes']}})
    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({"Id": url_for('batch.batch_get', id=id)})
    return resp


@batch.route("/api/batch/<id>", methods=["DELETE"])
def batch_delete(id):
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    resp = Response()

    if not existing:
        pass
    else:
        resp.status_code = 204
        resp.headers.add("Cache-Control", "no-cache")
        db.batch.delete_one({"_id": id})
        return resp


@batch.route("/api/batch/<id>/bins", methods=["GET"])
def batch_bins_get(id):
    resp = Response()
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))

    if not existing:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "This batch does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an existing batch id"
            }]
        })
        return resp

    resp.status_code = 200
    resp.mimetype = "application/json"

    contained_by_bins = [Bin.from_mongodb_doc(bson) for bson in db.bin.find(
        {f"contents.{id}": {"$exists": True}})]
    locations = {bin.id: {id: bin.contents[id]} for bin in contained_by_bins}

    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "state": locations
    })

    return resp
