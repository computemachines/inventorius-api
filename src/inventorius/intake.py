"""Commands for getting physical inventory into the append-only ledger."""

from flask import Blueprint, jsonify, request
from voluptuous.error import MultipleInvalid

from inventorius.db import db
from inventorius.auth import current_actor, require_capability
from inventorius.inventory_repository import (
    IdempotencyConflict,
    InventoryRepository,
    MissingBin,
    MissingSku,
)
from inventorius.util import IdentifierSpaceExhausted, no_cache
from inventorius.validation import intake_capture_schema
import inventorius.util_error_responses as problem


intake = Blueprint("intake", __name__)


@intake.route("/api/intake", methods=["POST"])
@require_capability("inventory.mutate")
@no_cache
def quick_capture():
    """Capture a provisional SKU, its first batch, and an initial receive.

    The idempotency record is stored on the immutable operation itself, so a
    retried scanner/client command returns its original result without issuing
    another label or changing the holding projection.
    """
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
        capture = intake_capture_schema(body)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)
    # One observation per exact external value.  Never normalize its case or
    # punctuation into a stronger ownership/association assertion.  An absent
    # optional list and an explicit empty list are the same command.
    capture["observed_codes"] = list(dict.fromkeys(capture.get("observed_codes", [])))

    try:
        stored = InventoryRepository(db).capture_intake(
            capture,
            idempotency_key=idempotency_key,
            actor=current_actor().durable_ref(),
        )
    except MissingBin as error:
        return problem.missing_bin_response(str(error))
    except MissingSku as error:
        return problem.missing_sku_response(str(error))
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    return jsonify({
        "status": "item captured",
        "state": stored.result,
    }), 200 if stored.replayed else 201
