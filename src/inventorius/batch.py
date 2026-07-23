from flask import Blueprint, jsonify, request, Response, url_for, after_this_request
from voluptuous.error import MultipleInvalid
from inventorius.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder
from inventorius.db import db
from inventorius.inventory_repository import (
    InventoryRepository,
    LedgerReferencedBatch,
    MissingBatch,
)
from inventorius.resource_models import BatchBinsEndpoint, BatchEndpoint
import inventorius.resource_operations as operation
from inventorius.resource_repository import (
    MissingResourceReference,
    ResourceIdempotencyConflict,
    ResourceIdentifierAlreadyUsed,
    ResourceRepository,
)
from inventorius.util import IdentifierSpaceExhausted, no_cache
from inventorius.validation import new_batch_schema, batch_patch_schema, prefixed_id, forced_schema, validate_url_id
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
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key:
        return problem.invalid_params_response_simple(
            "Idempotency-Key", "header is required"
        )
    if len(idempotency_key) > 200:
        return problem.invalid_params_response_simple(
            "Idempotency-Key", "must be at most 200 characters"
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple(
            "body", "must be a JSON object"
        )
    try:
        command = new_batch_schema(body)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    try:
        stored = ResourceRepository(db).create(
            "BAT",
            command,
            idempotency_key=idempotency_key,
        )
    except ResourceIdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )
    except ResourceIdentifierAlreadyUsed:
        return problem.duplicate_resource_response(
            "id", "has already been used"
        )
    except MissingResourceReference as error:
        return problem.invalid_params_response_simple(
            "sku_id", "must be an existing sku id"
        )
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    # Add text index if not yet created
    # TODO: This should probably be turned into a global flag
    if "name_text" not in db.batch.index_information().keys():
        db.batch.create_index([("name", TEXT)])

    return jsonify({
        "Id": url_for("batch.batch_get", id=stored.state["id"]),
        "status": "batch created",
        "state": stored.state,
    }), 200 if stored.replayed else 201


@batch.route("/api/batch/<id>", methods=["GET"])
@validate_url_id("BAT")
def batch_get(id):
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))

    if not existing:
        return problem.missing_batch_response(id)
    else:
        return BatchEndpoint.from_batch(existing).get_response()


@batch.route("/api/batch/<id>", methods=["PATCH"])
@validate_url_id("BAT")
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
@validate_url_id("BAT")
@no_cache
def batch_delete(id):
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))
    if not existing:
        return problem.missing_batch_response(id)

    try:
        InventoryRepository(db).delete_legacy_batch(id)
    except MissingBatch:
        # A concurrent command/delete transaction removed it after the
        # preliminary response-shaping read above.
        return problem.missing_batch_response(id)
    except LedgerReferencedBatch:
        # The precise reference is deliberately not exposed here: it can
        # change during a transaction retry, while the durable fact is that
        # this batch is no longer deletable.
        return problem.problem_response(status_code=403, json={
            "type": "resource-in-use",
            "title": "Can not delete a batch referenced by inventory history.",
            "invalid-params": [{
                "name": "id",
                "reason": "batch is referenced by inventory state or history",
            }],
        })

    return BatchEndpoint.from_batch(existing).deleted_success_response()


@batch.route("/api/batch/<id>/bins", methods=["GET"])
@validate_url_id("BAT")
def batch_bins_get(id):
    resp = Response()
    existing = Batch.from_mongodb_doc(db.batch.find_one({"_id": id}))

    if not existing:
        return problem.missing_batch_response(id)
    return BatchBinsEndpoint.from_id(id, retrieve=True).get_response()
