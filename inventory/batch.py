from flask import Blueprint, request, Response, url_for
from inventory.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import admin_increment_code

from pymongo import TEXT

import json

batch = Blueprint("batch", __name__)


@batch.route("/api/batches", methods=['POST'])
def batches_post():
    resp = Response()
    resp.headers = {"Cache-Control": "no-cache"}

    batch_id = request.json.get('id', None)

    if not batch_id:
        resp.status_code = 400
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-required-field",
            "title": "Batch Id is a required field.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be filled in"
            }]
        })
        return resp

    if not batch_id.startswith("BAT"):
        resp.status_code = 400
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "bad-id-format",
            "title": "Batch Ids must start with 'BAT'.",
            "invalid-params": [{
                "name": "id",
                "reason": "must start with 'BAT'"
            }]
        })
        return resp

    sku_id = request.json.get('sku_id', None)

    existing_batch = db.batch.find_one({"_id": batch_id})
    if existing_batch:
        resp.status_code = 409
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "duplicate-resource",
            "title": "Cannot create duplicate batch.",
            "invalid-params": [{
                "name": "id",
                "reason": "must not be an existing batch id",
            }]})
        return resp

    if sku_id:
        existing_sku = db.sku.find_one({"_id": sku_id})
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

    batch = Batch.from_json({
        "id": batch_id,
        "sku_id": sku_id,
        "name": request.json.get("name", None),
        "owned_codes": request.json.get("owned_codes", None),
        "associated_codes": request.json.get("associated_codes", None),
        "props": request.json.get("props", None)
    })

    admin_increment_code("BAT", batch_id)
    db.batch.insert_one(batch.to_mongodb_doc())

    # Add text index if not yet created
    # TODO: This should probably be turned into a global flag
    if "name_text" not in db.batch.index_information().keys():
        print("Creating text index for batch#name")
        db.sku.create_index([("name", TEXT)])

    resp.status_code = 201
    # resp.location = url_for("batch.batch_get", id=batch_id)

    return resp


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
            "state": json.loads(existing.to_json())
        })
        return resp


@batch.route("/api/batch/<id>", methods=["PATCH"])
def batch_patch(id):
    patch = request.json
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    resp = Response()
    resp.headers = {"Cache-Control": "no-cache"}

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

    if "sku_id" in patch.keys():
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
    resp.status_code = 204
    return resp


@batch.route("/api/batch/<id>", methods=["DELETE"])
def batch_delete(id):
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    resp = Response()

    if not existing:
        pass
    else:
        resp.status_code = 204
        resp.headers = {"Cache-Control": "no-cache"}
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
