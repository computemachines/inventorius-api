from flask import Blueprint, request, Response, url_for, after_this_request
from voluptuous.error import MultipleInvalid
from inventorius.data_models import Bin, DataModelJSONEncoder as Encoder
from inventorius.db import db
from inventorius.holding_queries import contents_for_bin
from inventorius.inventory_repository import (
    InventoryRepository,
    LedgerReferencedBin,
    MissingBin,
)
from inventorius.resource_models import BinEndpoint
from inventorius.util import get_body_type, admin_increment_code, no_cache
import inventorius.util_error_responses as problem
import inventorius.util_success_responses as success
from inventorius.validation import bin_patch_schema, new_bin_schema, validate_url_id

import json

bin = Blueprint("bin", __name__)


@bin.route('/api/bins', methods=['POST'])
@no_cache
def bins_post():
    try:
        json = new_bin_schema(request.json)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)
    
    existing = db.bin.find_one({'_id': json['id']})
    if existing:
        return problem.duplicate_resource_response("id")

    bin = Bin.from_json(json)
    admin_increment_code("BIN", bin.id)
    db.bin.insert_one(bin.to_mongodb_doc())
    return BinEndpoint.from_bin(bin).created_success_response()


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
        db.bin.update_one({"_id": id},
                          {"$set": {"props": json['props']}})

    return BinEndpoint.from_bin(existing).updated_success_response()


@bin.route('/api/bin/<id>', methods=['DELETE'])
@validate_url_id("BIN")
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
        return success.bin_deleted_response(id)
    return problem.dangerous_operation_unforced_response("id", "bin must be empty")
