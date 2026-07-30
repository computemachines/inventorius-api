from flask import Blueprint, jsonify, request, Response, url_for, after_this_request
from voluptuous.error import MultipleInvalid
from inventorius.data_models import Bin, DataModelJSONEncoder as Encoder
from inventorius.bin_repository import (
    BinIdempotencyConflict,
    BinIdentifierAlreadyUsed,
    BinRepository,
)
from inventorius.db import db
from inventorius.auth import current_actor, require_capability
from inventorius.mutation_receipts import record_mutation
from inventorius.holding_queries import contents_for_bin
from inventorius.inventory_repository import (
    InventoryRepository,
    LedgerReferencedBin,
    MissingBin,
)
from inventorius.resource_models import BinEndpoint
from inventorius.util import IdentifierSpaceExhausted, get_body_type, no_cache
import inventorius.util_error_responses as problem
import inventorius.util_success_responses as success
from inventorius.validation import bin_patch_schema, new_bin_schema, validate_url_id

import json

bin = Blueprint("bin", __name__)


@bin.route('/api/bins', methods=['POST'])
@require_capability("catalog.mutate")
@no_cache
def bins_post():
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
        command = new_bin_schema(body)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    try:
        stored = BinRepository(db).create(
            command,
            idempotency_key=idempotency_key,
            actor=current_actor().durable_ref(),
        )
    except BinIdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )
    except BinIdentifierAlreadyUsed:
        return problem.duplicate_resource_response(
            "id", "has already been used"
        )
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    return jsonify({
        "Id": url_for("bin.bin_get", id=stored.state["id"]),
        "status": "bin created",
        "state": stored.state,
    }), 200 if stored.replayed else 201


@bin.route('/api/bin/<id>', methods=['GET'])
@validate_url_id("BIN")
def bin_get(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    if existing is None:
        return problem.missing_bin_response(id)
    else:
        existing.contents = contents_for_bin({"_id": existing.id, "contents": existing.contents})
        return BinEndpoint.from_bin(existing).get_response()


@bin.route('/api/bin/<id>', methods=['PATCH'])
@validate_url_id("BIN")
@require_capability("catalog.mutate")
@no_cache
def bin_patch(id):
    try:
        json = bin_patch_schema(request.json)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    existing = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    if existing is None:
        problem.missing_bin_response(id)

    if "props" in json.keys():
        db.bin.update_one({"_id": id}, {"$set": {"props": json['props']}})
        record_mutation(
            db, kind="catalog.bin.update", target=id,
            actor=current_actor().durable_ref(),
        )

    return BinEndpoint.from_bin(existing).updated_success_response()


@bin.route('/api/bin/<id>', methods=['DELETE'])
@validate_url_id("BIN")
@require_capability("catalog.mutate")
@no_cache
def bin_delete(id):
    force = request.args.get('force', 'false') == 'true'
    try:
        deleted = InventoryRepository(db).delete_legacy_bin(id, force=force)
    except MissingBin:
        return problem.missing_bin_response(id)
    except LedgerReferencedBin:
        return problem.ledger_history_conflict_response(
            "id", "bin is referenced by immutable inventory operation history"
        )

    if deleted:
        record_mutation(
            db, kind="catalog.bin.delete", target=id,
            actor=current_actor().durable_ref(),
        )
        return success.bin_deleted_response(id)
    return problem.dangerous_operation_unforced_response("id", "bin must be empty")
