"""Commands for getting physical inventory into the system quickly."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, url_for
from pymongo import TEXT
from pymongo.errors import DuplicateKeyError
from voluptuous.error import MultipleInvalid

from inventorius.data_models import Sku
from inventorius.db import db
from inventorius.util import admin_get_next, admin_increment_code, no_cache
from inventorius.validation import quick_capture_schema
import inventorius.util_error_responses as problem


intake = Blueprint("intake", __name__)


@intake.route("/api/intake", methods=["POST"])
@no_cache
def quick_capture():
    """Create a minimally described SKU and place it in an existing bin.

    This is intentionally a command rather than two client-side requests. A
    successful response means both the identity and its physical placement
    exist. MongoDB is not configured as a replica set here, so the small
    compensating delete below protects against a bin disappearing between the
    validation and update steps.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple(
            "body", "must be a JSON object"
        )
    try:
        capture = quick_capture_schema(body)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)

    bin_id = capture["bin_id"]
    if not db.bin.find_one({"_id": bin_id}):
        return problem.missing_bin_response(bin_id)

    sku_id = admin_get_next("SKU")
    sku = Sku(
        id=sku_id,
        name=capture["description"],
        props={
            "_capture_status": "provisional",
            "_captured_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Keep the existing monotonically increasing label contract. A failed
    # insertion may burn an identifier, which is preferable to reusing one.
    admin_increment_code("SKU", sku_id)
    try:
        db.sku.insert_one(sku.to_mongodb_doc())
    except DuplicateKeyError:
        return problem.duplicate_resource_response("id")

    placement = db.bin.update_one(
        {"_id": bin_id},
        {"$inc": {f"contents.{sku_id}": capture["quantity"]}},
    )
    if placement.matched_count != 1:
        db.sku.delete_one({"_id": sku_id})
        return problem.missing_bin_response(bin_id)

    if "name_text" not in db.sku.index_information():
        db.sku.create_index([("name", TEXT)])

    return jsonify({
        "Id": url_for("sku.sku_get", id=sku_id),
        "status": "item captured",
        "state": {
            "sku_id": sku_id,
            "bin_id": bin_id,
            "quantity": capture["quantity"],
            "description": capture["description"],
            "provisional": True,
        },
    }), 201
