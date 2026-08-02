"""HTTP boundary for quantity-native physical evidence and withdrawals."""

from __future__ import annotations

from fractions import Fraction
import re

from flask import Blueprint, jsonify, request
from voluptuous.error import Invalid, MultipleInvalid

from inventorius.auth import current_actor, require_capability
from inventorius.db import db
from inventorius.inventory_repository import MissingBatch, MissingBin
from inventorius.ledger import IdempotencyConflict
from inventorius.quantity_codec import claim_from_input
from inventorius.quantity_constraints import QuantityDomain
from inventorius.quantity_projection import (
    QuantityProjectionError,
    quantity_holding_resource,
    quantity_holding_resources,
)
from inventorius.quantity_repository import (
    MissingQuantityHolding,
    QuantityRepository,
    QuantitySupersessionRejected,
)
from inventorius.util import no_cache
from inventorius.validation import (
    prefixed_id,
    quantity_observation_command_schema,
    quantity_withdrawal_command_schema,
)
import inventorius.util_error_responses as problem


quantity_routes = Blueprint("quantity_routes", __name__)


def _idempotency_key_error():
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        return None, problem.invalid_params_response_simple(
            "Idempotency-Key", "header is required"
        )
    if len(key) > 200:
        return None, problem.invalid_params_response_simple(
            "Idempotency-Key", "must be at most 200 characters"
        )
    return key, None


def _claim_command(body):
    try:
        command = quantity_observation_command_schema(body)
        claim = claim_from_input(command["claim"])
        domain = QuantityDomain(command["domain"])
    except MultipleInvalid:
        raise
    except ValueError as error:
        raise MultipleInvalid([Invalid(str(error), ["claim"])]) from error
    if command["claim"]["domain"] != domain.value:
        raise MultipleInvalid([Invalid(
            "claim domain must match holding domain", ["claim", "domain"]
        )])
    values = (claim.lower, claim.preferred, claim.upper, claim.capacity)
    if domain == QuantityDomain.DISCRETE and any(
        value is not None and value.denominator != 1 for value in values
    ):
        raise MultipleInvalid([Invalid(
            "discrete claims must use whole amounts", ["claim"]
        )])
    if domain == QuantityDomain.DISCRETE and command["unit"] != "each":
        raise MultipleInvalid([Invalid(
            "discrete observations currently use the 'each' unit", ["unit"]
        )])
    if domain == QuantityDomain.CONTINUOUS and command["unit"] == "each":
        raise MultipleInvalid([Invalid(
            "continuous observations need a measured unit", ["unit"]
        )])
    command["domain"] = domain
    command["claim"] = claim
    command.setdefault("packaging_configuration_id", None)
    return command


@quantity_routes.route("/api/quantity-holdings", methods=["GET"])
@no_cache
def quantity_holdings_get():
    """Return physical evidence streams by Batch and/or location."""
    batch_id = request.args.get("batch_id")
    location_id = request.args.get("location_id")
    if batch_id is None and location_id is None:
        return problem.invalid_params_response_simple(
            "batch_id", "batch_id or location_id is required"
        )
    try:
        if batch_id is not None:
            batch_id = prefixed_id("BAT")(batch_id)
        if location_id is not None:
            location_id = prefixed_id("BIN")(location_id)
    except Invalid as error:
        return problem.invalid_params_response(MultipleInvalid([error]))
    try:
        holdings = quantity_holding_resources(
            db, batch_id=batch_id, location_id=location_id
        )
    except QuantityProjectionError as error:
        return problem.problem_response(status_code=500, json={
            "type": "quantity-history-invalid",
            "title": "Stored quantity evidence could not be replayed.",
            "detail": str(error),
        })
    return jsonify({"state": {"holdings": holdings}})


@quantity_routes.route("/api/quantity-holdings/<stream_id>", methods=["GET"])
@no_cache
def quantity_holding_get(stream_id):
    if re.fullmatch(r"QSH[0-9a-f]{32}", stream_id) is None:
        return problem.invalid_params_response_simple(
            "stream_id", "must be a quantity holding identifier"
        )
    if db.quantity_heads.find_one({"_id": stream_id}, {"_id": 1}) is None:
        return problem.missing_resource_response(
            f"/api/quantity-holdings/{stream_id}"
        )
    try:
        resource = quantity_holding_resource(db, stream_id)
    except QuantityProjectionError as error:
        return problem.problem_response(status_code=500, json={
            "type": "quantity-history-invalid",
            "title": "Stored quantity evidence could not be replayed.",
            "detail": str(error),
        })
    return jsonify({"state": resource})


@quantity_routes.route("/api/quantity-observations", methods=["POST"])
@require_capability("inventory.mutate")
@no_cache
def quantity_observations_post():
    idempotency_key, error_response = _idempotency_key_error()
    if error_response is not None:
        return error_response
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple(
            "body", "must be a JSON object"
        )
    try:
        command = _claim_command(body)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)
    try:
        stored = QuantityRepository(db).record_observation(
            command,
            idempotency_key=idempotency_key,
            actor=current_actor().durable_ref(),
        )
    except MissingBatch as error:
        return problem.missing_batch_response(str(error))
    except MissingBin as error:
        return problem.missing_bin_response(str(error))
    except MissingQuantityHolding:
        return problem.problem_response(status_code=409, json={
            "type": "missing-quantity-holding",
            "title": "This holding does not have a physical quantity stream.",
        })
    except QuantitySupersessionRejected as error:
        return problem.problem_response(status_code=409, json={
            "type": "quantity-supersession-rejected",
            "title": "That earlier quantity claim cannot be superseded.",
            "detail": str(error),
        })
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )
    resource = quantity_holding_resource(db, stored.result["stream_id"])
    return jsonify({
        "status": "quantity observation recorded",
        "state": {"observation": stored.result, "holding": resource},
    }), 200 if stored.replayed else 201


@quantity_routes.route("/api/quantity-withdrawals", methods=["POST"])
@require_capability("inventory.mutate")
@no_cache
def quantity_withdrawals_post():
    idempotency_key, error_response = _idempotency_key_error()
    if error_response is not None:
        return error_response
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple(
            "body", "must be a JSON object"
        )
    try:
        command = quantity_withdrawal_command_schema(body)
        command["domain"] = QuantityDomain(command["domain"])
        amount = Fraction(command["amount"])
        if (
            command["domain"] == QuantityDomain.DISCRETE
            and amount.denominator != 1
        ):
            raise MultipleInvalid([Invalid(
                "discrete withdrawals must use a whole amount", ["amount"]
            )])
        command.setdefault("packaging_configuration_id", None)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)
    try:
        stored = QuantityRepository(db).record_withdrawal(
            command,
            idempotency_key=idempotency_key,
            actor=current_actor().durable_ref(),
        )
    except MissingBatch as error:
        return problem.missing_batch_response(str(error))
    except MissingBin as error:
        return problem.missing_bin_response(str(error))
    except MissingQuantityHolding:
        return problem.problem_response(status_code=409, json={
            "type": "missing-quantity-holding",
            "title": "This holding does not have a physical quantity stream.",
        })
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )
    stream_id = db.inventory_operations.find_one(
        {"_id": stored.result["operation_id"]},
        {"quantity_effect.stream_id": 1},
    )["quantity_effect"]["stream_id"]
    resource = quantity_holding_resource(db, stream_id)
    return jsonify({
        "status": "quantity withdrawal recorded",
        "state": {"operation": stored.result, "holding": resource},
    }), 200 if stored.replayed else 201
