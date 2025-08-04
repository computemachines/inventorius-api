from flask import Blueprint, request, Response, url_for, after_this_request
from voluptuous.error import MultipleInvalid
from inventorius.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder
from inventorius.db import db
from inventorius.resource_models import BatchBinsEndpoint, BatchEndpoint
import inventorius.resource_operations as operation
from inventorius.util import admin_increment_code, check_code_list, no_cache
from inventorius.validation import new_batch_schema, batch_patch_schema, prefixed_id, forced_schema
from voluptuous import All, Required
import inventorius.util_error_responses as problem
import inventorius.util_success_responses as success

from pymongo import TEXT
from bson.decimal128 import Decimal128

import json

batch = Blueprint("batch", __name__)


@batch.route("/api/batches", methods=['POST'])
@no_cache
def batches_post():
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

    admin_increment_code("BAT", batch.id)
    db.batch.insert_one(batch.to_mongodb_doc())

    # Add text index if not yet created
    # TODO: This should probably be turned into a global flag
    if "name_text" not in db.batch.index_information().keys():
        db.sku.create_index([("name", TEXT)])

    return BatchEndpoint.from_batch(batch).created_success_response()


@batch.route("/api/batch/<id>", methods=["GET"])
def batch_get(id):
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))

    if not existing:
        return problem.missing_batch_response(id)
    else:
        return BatchEndpoint.from_batch(existing).get_response()


@batch.route("/api/batch/<id>", methods=["PATCH"])
@no_cache
def batch_patch(id):
    try:
        # must be batch patch, where json["id"] is prefixed and equals id
        json = batch_patch_schema.extend(
            {Required("id"): All(prefixed_id("BAT"), id)})(request.json)
        forced = forced_schema(request.args).get("force")
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    existing_batch = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    if not existing_batch:
        return problem.missing_batch_response(id)

    if json.get("sku_id"):
        existing_sku = db.sku.find_one({"_id": json['sku_id']})
        if not existing_sku:
            return problem.invalid_params_response(problem.missing_resource_param_error("sku_id", "must be an existing sku id"))

    if (existing_batch.sku_id
        and "sku_id" in json
        and existing_batch.sku_id != json["sku_id"]
            and not forced):
        return problem.dangerous_operation_unforced_response("sku_id", "The sku of this batch has already been set. Can not change without force=true.")

    new_batch_doc = Batch.from_json({"_id": id, **json}).to_mongodb_doc()

    if "props" in json.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"props": new_batch_doc['props']}})
    if "name" in json.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"name": new_batch_doc['name']}})

    if "sku_id" in json.keys():
        if not json["sku_id"]:
            db.batch.update_one({"_id": id}, {"$unset": {"sku_id": ""}})
        else:
            db.batch.update_one({"_id": id},
                                {"$set": {"sku_id": json['sku_id']}})

    if "owned_codes" in json.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"owned_codes": json['owned_codes']}})
    if "associated_codes" in json.keys():
        db.batch.update_one({"_id": id},
                            {"$set": {"associated_codes": json['associated_codes']}})

    updated_batch = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    return BatchEndpoint.from_batch(updated_batch).redirect_response(False)


@batch.route("/api/batch/<id>", methods=["DELETE"])
@no_cache
def batch_delete(id):
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    if not existing:
        return problem.missing_batch_response(id)
    else:
        db.batch.delete_one({"_id": id})
        return BatchEndpoint.from_batch(existing).deleted_success_response()


@batch.route("/api/batch/<id>/bins", methods=["GET"])
def batch_bins_get(id):
    resp = Response()
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))

    if not existing:
        return problem.missing_batch_response(id)
    return BatchBinsEndpoint.from_id(id, retrieve=True).get_response()
