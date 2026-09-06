from flask import Blueprint, jsonify, request, Response, url_for
from voluptuous.error import MultipleInvalid
from voluptuous.schema_builder import Required
from inventorius.data_models import Sku, Bin, Batch, DataModelJSONEncoder as Encoder
from inventorius.db import db
from inventorius.sku_properties import sku_display_name
from inventorius.auth import current_actor, require_capability
from inventorius.mutation_receipts import record_mutation
from inventorius.inventory_repository import (
    InventoryRepository,
    LedgerReferencedSku,
    MissingSku,
)
from inventorius.holding_queries import locations_for_sku
from inventorius.resource_repository import (
    ResourceIdempotencyConflict,
    ResourceIdentifierAlreadyUsed,
    ResourceRepository,
)
from inventorius.util import IdentifierSpaceExhausted, no_cache
from inventorius.validation import new_sku_schema, prefixed_id, sku_patch_schema, validate_url_id
import inventorius.util_error_responses as problem
from inventorius.resource_models import SkuEndpoint

from pymongo import TEXT

import json

sku = Blueprint("sku", __name__)


@ sku.route('/api/skus', methods=['POST'])
@require_capability("catalog.mutate")
@no_cache
def skus_post():
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
        command = new_sku_schema(body)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    try:
        sku_display_name(command.get("props"), command.get("name"))
    except ValueError as error:
        return problem.invalid_params_response_simple("props.name", str(error))

    try:
        stored = ResourceRepository(db).create(
            "SKU",
            command,
            idempotency_key=idempotency_key,
            actor=current_actor().durable_ref(),
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
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    # Add text index if not yet created
    # TODO: This should probably be turned into a global flag
    if "name_text" not in db.sku.index_information().keys():
        # print("Creating text index for sku#name") # was too noisy
        db.sku.create_index([("name", TEXT)])
    return jsonify({
        "Id": url_for("sku.sku_get", id=stored.state["id"]),
        "status": "sku created",
        "state": stored.state,
    }), 200 if stored.replayed else 201



@sku.route('/api/sku/<id>', methods=['GET'])
@validate_url_id("SKU")
def sku_get(id):
    # detailed = request.args.get("details") == "true"

    sku = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))
    if sku is None:
        return problem.missing_bin_response(id)
    return SkuEndpoint.from_sku(sku).get_response()


@ sku.route('/api/sku/<id>', methods=['PATCH'])
@validate_url_id("SKU")
@require_capability("catalog.mutate")
@no_cache
def sku_patch(id):
    try:
        json = sku_patch_schema.extend({"id": prefixed_id("SKU", id)})(request.json)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    existing = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))
    if not existing:
        return problem.invalid_params_response(problem.missing_resource_param_error("id"))

    updates = {key: json[key] for key in ("owned_codes", "associated_codes", "props") if key in json}
    original_props = existing.props or {}
    props = dict(json.get("props") or {}) if "props" in json else dict(original_props)
    try:
        if "name" in props:
            # Old clients may still edit the top-level name. An explicitly
            # supplied property wins when both representations are present.
            if "name" in json and "props" not in json:
                props["name"] = json["name"] or ""
                updates["props"] = props
            updates["name"] = sku_display_name(props)
        elif "name" in json:
            updates["name"] = json["name"]
            if "name" in original_props:
                props["name"] = json["name"] or ""
                updates["props"] = props
        elif "props" in json and "name" in original_props:
            updates["name"] = ""
    except ValueError as error:
        return problem.invalid_params_response_simple("props.name", str(error))
    if updates:
        # Keep the property and its search/display projection in one write.
        db.sku.update_one({"_id": id}, {"$set": updates})

    updated_sku = Sku.from_mongodb_doc(db.sku.find_one({"_id": id}))
    record_mutation(
        db, kind="catalog.sku.update", target=id,
        actor=current_actor().durable_ref(),
    )
    return SkuEndpoint.from_sku(updated_sku).updated_success_response()

@ sku.route('/api/sku/<id>', methods=['DELETE'])
@validate_url_id("SKU")
@require_capability("catalog.mutate")
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

    try:
        InventoryRepository(db).delete_legacy_sku(id)
    except MissingSku:
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
    except LedgerReferencedSku as error:
        resp.status_code = 403
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "resource-in-use",
            "title": "Can not delete a SKU that is still referenced.",
            "invalid-params": [{
                "name": "id",
                "reason": f"SKU is referenced by {error}",
            }],
        })
        return resp

    resp.status_code = 204
    record_mutation(
        db, kind="catalog.sku.delete", target=id,
        actor=current_actor().durable_ref(),
    )
    return resp


@ sku.route('/api/sku/<id>/bins', methods=['GET'])
@validate_url_id("SKU")
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

    locations = locations_for_sku(id)

    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "state": locations
    })

    return resp


@ sku.route('/api/sku/<id>/batches', methods=['GET'])
@validate_url_id("SKU")
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
