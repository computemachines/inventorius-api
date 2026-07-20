"""Canonical receive, transfer, and release commands for ledger inventory."""

from flask import Blueprint, jsonify, request
from voluptuous.error import MultipleInvalid

from inventorius.db import db
from inventorius.inventory_repository import (
    IdempotencyConflict,
    InsufficientHolding,
    InventoryRepository,
    MissingBatch,
    MissingBin,
)
from inventorius.util import no_cache
from inventorius.validation import inventory_operation_command_schema
import inventorius.util_error_responses as problem


inventory_operations = Blueprint("inventory_operations", __name__)


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


@inventory_operations.route("/api/inventory-operations", methods=["POST"])
@no_cache
def inventory_operations_post():
    """Append a physical receive, transfer, or release operation.

    A client submits the user-facing command, not ledger legs.  The server
    derives the immutable debit/credit representation after checking the
    batch and every named bin in one Mongo transaction.
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
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )

    return jsonify({
        "status": "inventory operation recorded",
        "state": stored.result,
    }), 200 if stored.replayed else 201
