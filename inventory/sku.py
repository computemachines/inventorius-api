from flask import Blueprint, request, Response, url_for
from voluptuous.error import MultipleInvalid
from inventory.data_models import Sku, Bin, Batch, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import admin_increment_code, check_code_list, no_cache
from inventory.validation import new_sku_schema, sku_patch_schema
import inventory.util_error_responses as problem
from inventory.resource_models import SkuEndpoint

from pymongo import TEXT

import json

sku = Blueprint("sku", __name__)


@ sku.route('/api/skus', methods=['POST'])
@no_cache
def skus_post():
    try:
        json = new_sku_schema(request.json)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    if db.sku.find_one({'_id': json['id']}):
        return problem.duplicate_resource_response("id")

    sku = Sku.from_json(json)
    admin_increment_code("SKU", sku.id)
    db.sku.insert_one(sku.to_mongodb_doc())
    # dbSku = Sku.from_mongodb_doc(db.sku.find_one({'id': sku.id}))

    # Add text index if not yet created
    # TODO: This should probably be turned into a global flag
    if "name_text" not in db.sku.index_information().keys():
        # print("Creating text index for sku#name") # was too noisy
        db.sku.create_index([("name", TEXT)])
    return SkuEndpoint.from_sku(sku).created_success_response()



@sku.route('/api/sku/<id>', methods=['GET'])
def sku_get(id):
    # detailed = request.args.get("details") == "true"

    sku = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))
    if sku is None:
        return problem.missing_bin_response(id)
    return SkuEndpoint.from_sku(sku).get_response()


@ sku.route('/api/sku/<id>', methods=['PATCH'])
@no_cache
def sku_patch(id):
    existing = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))
    if existing is None:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "Can not edit sku that does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an exisiting sku id"
            }]
        })
        return resp

    if "owned_codes" in patch:
        db.sku.update_one({"_id": id},
                          {"$set": {"owned_codes": patch["owned_codes"]}})
    if "associated_codes" in patch:
        db.sku.update_one({"_id": id},
                          {"$set": {"associated_codes": patch["associated_codes"]}})
    if "name" in patch:
        db.sku.update_one({"_id": id},
                          {"$set": {"name": patch["name"]}})
    if "props" in patch:
        db.sku.update_one({"_id": id},
                          {"$set": {"props": patch["props"]}})

    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("sku.sku_get", id=existing.id),
    })
    return resp


@ sku.route('/api/sku/<id>', methods=['DELETE'])
def sku_delete(id):
    existing = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))

    resp = Response()
    resp.headers.add("Cache-Control", "no-cache")

    if existing is None:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "Can not delete sku that does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an exisiting sku id"
            }]
        })
        return resp

    num_contained_by_bins = db.bin.count_documents(
        {f"contents.{id}": {"$exists": True}})
    if num_contained_by_bins > 0:
        resp.status_code = 403
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "resource-in-use",
            "title": "Can not delete sku that is being used. Try releasing all instances of this sku.",
            "invalid-params": {
                "name": "id",
                "reason": "must be an unused sku"
            }
        })
        return resp

    db.sku.delete_one({"_id": existing.id})
    resp.status_code = 204
    return resp


@ sku.route('/api/sku/<id>/bins', methods=['GET'])
def sku_bins_get(id):
    resp = Response()

    existing = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))
    if not existing:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "Can not get locations of sku that does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an exisiting sku id"
            }]
        })
        return resp

    contained_by_bins = [Bin.from_mongodb_doc(bson) for bson in db.bin.find(
        {f"contents.{id}": {"$exists": True}})]
    locations = {bin.id: {id: bin.contents[id]} for bin in contained_by_bins}

    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "state": locations
    })

    return resp


@ sku.route('/api/sku/<id>/batches', methods=['GET'])
def sku_batches_get(id):
    resp = Response()

    existing = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))
    if not existing:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "Can not get batches for a sku that does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an exisiting sku id"
            }]
        })
        return resp

    batches = [Batch.from_mongodb_doc(bson).id
               for bson in db.batch.find({"sku_id": id})]
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "state": batches
    })

    return resp
