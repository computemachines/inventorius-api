"""HTTP boundary for contextual inventory Batch resolution."""

from flask import Blueprint, jsonify, request
from voluptuous.error import Invalid

from inventorius.db import db
from inventorius.inventory_resolution import resolve_inventory_candidates
from inventorius.util import no_cache
from inventorius.validation import normalize_prefixed_id
import inventorius.util_error_responses as problem


inventory_candidates = Blueprint("inventory_candidates", __name__)

MAX_EVIDENCE_VALUES = 50
MAX_EVIDENCE_LENGTH = 500
DEFAULT_LIMIT = 50
MAX_LIMIT = 50


def _validated_evidence():
    raw_values = request.args.getlist("evidence")
    if len(raw_values) > MAX_EVIDENCE_VALUES:
        return None, problem.invalid_params_response_simple(
            "evidence", f"must contain at most {MAX_EVIDENCE_VALUES} values"
        )

    evidence = []
    seen = set()
    for raw_value in raw_values:
        if len(raw_value) > MAX_EVIDENCE_LENGTH:
            return None, problem.invalid_params_response_simple(
                "evidence", f"each value must be at most {MAX_EVIDENCE_LENGTH} characters"
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in raw_value):
            return None, problem.invalid_params_response_simple(
                "evidence", "must not contain control characters"
            )
        value = raw_value.strip()
        if not value:
            return None, problem.invalid_params_response_simple(
                "evidence", "must not contain blank values"
            )
        if value not in seen:
            seen.add(value)
            evidence.append(value)
    return evidence, None


def _validated_source_location():
    source_values = request.args.getlist("source_location_id")
    if len(source_values) > 1:
        return None, problem.invalid_params_response_simple(
            "source_location_id", "must be provided at most once"
        )
    if not source_values:
        return None, None
    try:
        source_location_id = normalize_prefixed_id(
            source_values[0], "BIN"
        )
    except Invalid as error:
        return None, problem.invalid_params_response_simple(
            "source_location_id", error.msg
        )
    if db.bin.find_one({"_id": source_location_id}, {"_id": 1}) is None:
        return None, problem.missing_bin_response(source_location_id)
    return source_location_id, None


def _validated_nonnegative_integer(name, default, *, minimum=0, maximum=None):
    values = request.args.getlist(name)
    if len(values) > 1:
        return None, problem.invalid_params_response_simple(
            name, "must be provided at most once"
        )
    if not values:
        return default, None
    try:
        value = int(values[0])
    except (TypeError, ValueError):
        return None, problem.invalid_params_response_simple(name, "must be an integer")
    if value < minimum:
        return None, problem.invalid_params_response_simple(
            name, f"must be at least {minimum}"
        )
    if maximum is not None and value > maximum:
        return None, problem.invalid_params_response_simple(
            name, f"must be at most {maximum}"
        )
    return value, None


@inventory_candidates.route("/api/inventory-candidates", methods=["GET"])
@no_cache
def inventory_candidates_get():
    evidence, validation_error = _validated_evidence()
    if validation_error is not None:
        return validation_error
    source_location_id, validation_error = _validated_source_location()
    if validation_error is not None:
        return validation_error
    limit, validation_error = _validated_nonnegative_integer(
        "limit", DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT
    )
    if validation_error is not None:
        return validation_error
    starting_from, validation_error = _validated_nonnegative_integer(
        "starting_from", 0
    )
    if validation_error is not None:
        return validation_error

    return jsonify({
        "state": resolve_inventory_candidates(
            db,
            evidence,
            source_location_id=source_location_id,
            limit=limit,
            starting_from=starting_from,
        )
    })
