"""Canonical receive, transfer, and release commands for ledger inventory."""

import re

from flask import Blueprint, jsonify, request
from voluptuous.error import MultipleInvalid

from inventorius.db import db
from inventorius.auth import current_actor, require_capability
from inventorius.inventory_repository import (
    CorrectionRejected,
    IdempotencyConflict,
    InsufficientHolding,
    InventoryRepository,
    MissingBatch,
    MissingBin,
    MissingInventoryOperation,
)
from inventorius.quantity_repository import QuantityManagedHolding
from inventorius.util import no_cache
from inventorius.validation import (
    inventory_correction_command_schema,
    inventory_operation_command_schema,
)
import inventorius.util_error_responses as problem


inventory_operations = Blueprint("inventory_operations", __name__)


def _operation_id_error(operation_id):
    if (
        not isinstance(operation_id, str)
        or re.fullmatch(r"OP[0-9a-f]{32}", operation_id) is None
    ):
        return problem.invalid_params_response_simple(
            "operation_id",
            "must be an inventory operation identifier",
        )
    return None


def _idempotency_key_error():
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key:
        return None, problem.invalid_params_response_simple(
            "Idempotency-Key", "header is required"
        )
    if len(idempotency_key) > 200:
        return None, problem.invalid_params_response_simple(
            "Idempotency-Key", "must be at most 200 characters"
        )
    return idempotency_key, None


def _correction_rejected_response(error):
    return problem.problem_response(status_code=409, json={
        "type": "correction-rejected",
        "title": "The selected receipt cannot be corrected this way.",
        "blocker": error.code,
        "detail": error.detail,
    })


def _location_contract_error(command):
    """Return a validation response when locations do not match the command."""
    kind = command["kind"]
    location_id = command.get("location_id")
    source_location_id = command.get("source_location_id")
    destination_location_id = command.get("destination_location_id")

    if kind == "receive":
        if location_id is None:
            return problem.invalid_params_response_simple(
                "location_id", "is required for receive"
            )
        if source_location_id is not None:
            return problem.invalid_params_response_simple(
                "source_location_id", "is not valid for receive"
            )
        if destination_location_id is not None:
            return problem.invalid_params_response_simple(
                "destination_location_id", "is not valid for receive"
            )
    elif kind == "release":
        if location_id is None:
            return problem.invalid_params_response_simple(
                "location_id", "is required for release"
            )
        if source_location_id is not None:
            return problem.invalid_params_response_simple(
                "source_location_id", "is not valid for release"
            )
        if destination_location_id is not None:
            return problem.invalid_params_response_simple(
                "destination_location_id", "is not valid for release"
            )
    else:
        if source_location_id is None:
            return problem.invalid_params_response_simple(
                "source_location_id", "is required for transfer"
            )
        if destination_location_id is None:
            return problem.invalid_params_response_simple(
                "destination_location_id", "is required for transfer"
            )
        if source_location_id == destination_location_id:
            return problem.invalid_params_response_simple(
                "destination_location_id", "must differ from source_location_id"
            )
        if location_id is not None:
            return problem.invalid_params_response_simple(
                "location_id", "is not valid for transfer"
            )
    return None


@inventory_operations.route("/api/inventory-operations", methods=["GET"])
@no_cache
def inventory_operations_get():
    """Return a bounded, sanitized, newest-first receipt list."""
    raw_limit = request.args.get("limit", "25")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 0
    if limit < 1 or limit > 100:
        return problem.invalid_params_response_simple(
            "limit", "must be a whole number from 1 through 100"
        )
    receipts = InventoryRepository(db).recent_receipts(limit=limit)
    return jsonify({"state": {"operations": receipts}})


@inventory_operations.route(
    "/api/inventory-operations/<operation_id>",
    methods=["GET"],
)
@no_cache
def inventory_operation_get(operation_id):
    """Return one sanitized receipt and the Batch's current exact holdings."""
    operation_id_error = _operation_id_error(operation_id)
    if operation_id_error is not None:
        return operation_id_error
    receipt = InventoryRepository(db).receipt(operation_id)
    if receipt is None:
        return problem.missing_resource_response(
            f"/api/inventory-operations/{operation_id}"
        )
    return jsonify({"state": receipt})


@inventory_operations.route("/api/inventory-operations", methods=["POST"])
@require_capability("inventory.mutate")
@no_cache
def inventory_operations_post():
    """Append a physical receive, transfer, or release operation.

    A client submits the user-facing command, not ledger legs.  The server
    derives the immutable debit/credit representation after checking the
    batch and every named bin in one Mongo transaction.
    """
    idempotency_key, idempotency_error = _idempotency_key_error()
    if idempotency_error is not None:
        return idempotency_error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple("body", "must be a JSON object")
    try:
        command = inventory_operation_command_schema(body)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)

    command.setdefault("packaging_configuration_id", None)
    if command["kind"] != "receive" and "observed_codes" in command:
        return problem.invalid_params_response_simple(
            "observed_codes", "is only valid for receive"
        )
    if "observed_codes" in command:
        # The physical evidence is retained exactly as scanned (aside from the
        # input schema's trimming), while command equality treats its order
        # and repeats as incidental.
        command["observed_codes"] = list(dict.fromkeys(command["observed_codes"]))
    location_error = _location_contract_error(command)
    if location_error is not None:
        return location_error

    try:
        stored = InventoryRepository(db).execute_inventory_command(
            command,
            idempotency_key=idempotency_key,
            actor=current_actor().durable_ref(),
        )
    except MissingBatch as error:
        return problem.missing_batch_response(str(error))
    except MissingBin as error:
        return problem.missing_bin_response(str(error))
    except InsufficientHolding:
        return problem.problem_response(status_code=409, json={
            "type": "insufficient-quantity",
            "title": problem.problem_titles["insufficient-quantity"],
            "invalid-params": [{
                "name": "quantity",
                "reason": "would make the source holding negative",
            }],
        })
    except QuantityManagedHolding:
        return problem.problem_response(status_code=409, json={
            "type": "quantity-managed-holding",
            "title": "This holding uses physical quantity evidence.",
            "detail": (
                "Use the quantity observation or withdrawal command instead "
                "of treating an estimate as exact available inventory."
            ),
        })
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )

    return jsonify({
        "status": "inventory operation recorded",
        "state": stored.result,
    }), 200 if stored.replayed else 201


@inventory_operations.route(
    "/api/inventory-operations/<original_operation_id>/corrections",
    methods=["POST"],
)
@require_capability("inventory.mutate")
@no_cache
def inventory_operation_correction_post(original_operation_id):
    """Append a constrained replacement correction for one intake receipt."""
    operation_id_error = _operation_id_error(original_operation_id)
    if operation_id_error is not None:
        return operation_id_error
    idempotency_key, idempotency_error = _idempotency_key_error()
    if idempotency_error is not None:
        return idempotency_error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple(
            "body", "must be a JSON object"
        )
    try:
        intended_state = inventory_correction_command_schema(body)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)

    repository = InventoryRepository(db)
    try:
        stored = repository.correct_inventory_operation(
            original_operation_id,
            intended_state,
            idempotency_key=idempotency_key,
            actor=current_actor().durable_ref(),
        )
    except MissingInventoryOperation:
        return problem.missing_resource_response(
            f"/api/inventory-operations/{original_operation_id}"
        )
    except MissingBatch as error:
        return problem.missing_batch_response(str(error))
    except MissingBin as error:
        return problem.missing_bin_response(str(error))
    except InsufficientHolding:
        return problem.problem_response(status_code=409, json={
            "type": "insufficient-quantity",
            "title": problem.problem_titles["insufficient-quantity"],
            "detail": (
                "The original received quantity is no longer available at "
                "the holding this correction must debit."
            ),
        })
    except CorrectionRejected as error:
        return _correction_rejected_response(error)
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )

    receipt = repository.receipt(stored.result["operation_id"])
    return jsonify({
        "status": "inventory operation corrected",
        "state": receipt,
    }), 200 if stored.replayed else 201
