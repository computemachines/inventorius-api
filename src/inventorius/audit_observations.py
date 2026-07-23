"""HTTP boundary for durable, non-reconciling physical-count evidence."""

import re

from flask import Blueprint, jsonify, request
from voluptuous.error import MultipleInvalid

from inventorius.audit_observation import (
    AuditCountsRejected,
    AuditObservationRepository,
    AuditSnapshotBlocked,
    AuditSnapshotStale,
)
from inventorius.db import db
from inventorius.inventory_repository import (
    AuditReconciliationRejected,
    InsufficientHolding,
    InventoryRepository,
    MissingAuditObservation,
    MissingBatch,
    MissingBin,
)
from inventorius.ledger import IdempotencyConflict
from inventorius.util import no_cache
from inventorius.validation import (
    audit_observation_command_schema,
    audit_reconciliation_command_schema,
)
import inventorius.util_error_responses as problem


audit_observations = Blueprint("audit_observations", __name__)


def _idempotency_key_error():
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key:
        return None, problem.invalid_params_response_simple(
            "Idempotency-Key",
            "header is required",
        )
    if len(idempotency_key) > 200:
        return None, problem.invalid_params_response_simple(
            "Idempotency-Key",
            "must be at most 200 characters",
        )
    return idempotency_key, None


def _observation_id_error(observation_id):
    if (
        not isinstance(observation_id, str)
        or re.fullmatch(r"AOB[0-9a-f]{32}", observation_id) is None
    ):
        return problem.invalid_params_response_simple(
            "observation_id",
            "must be an audit observation identifier",
        )
    return None


@audit_observations.route("/api/audit-observations", methods=["GET"])
@no_cache
def audit_observations_get():
    """Return a bounded, newest-first list of sanitized observations."""
    raw_limit = request.args.get("limit", "25")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 0
    if limit < 1 or limit > 100:
        return problem.invalid_params_response_simple(
            "limit",
            "must be a whole number from 1 through 100",
        )
    observations = AuditObservationRepository(db).recent_observations(
        limit=limit
    )
    return jsonify({"state": {"observations": observations}})


@audit_observations.route(
    "/api/audit-observations/<observation_id>",
    methods=["GET"],
)
@no_cache
def audit_observation_get(observation_id):
    """Return one sanitized immutable physical-count observation."""
    observation_id_error = _observation_id_error(observation_id)
    if observation_id_error is not None:
        return observation_id_error
    observation = AuditObservationRepository(db).observation(observation_id)
    if observation is None:
        return problem.missing_resource_response(
            f"/api/audit-observations/{observation_id}"
        )
    return jsonify({"state": observation})


@audit_observations.route("/api/audit-observations", methods=["POST"])
@no_cache
def audit_observations_post():
    """Append reviewed physical evidence without changing inventory state."""
    idempotency_key, idempotency_error = _idempotency_key_error()
    if idempotency_error is not None:
        return idempotency_error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple(
            "body",
            "must be a JSON object",
        )
    try:
        command = audit_observation_command_schema(body)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)

    seen_identities = set()
    for count in command["counts"]:
        identity = (
            count["batch_id"],
            count["unit"],
            count.get("packaging_configuration_id"),
        )
        if identity in seen_identities:
            return problem.invalid_params_response_simple(
                "counts",
                "must not contain duplicate holding identities",
            )
        seen_identities.add(identity)

    command["unresolved_evidence"] = list(dict.fromkeys(
        command.get("unresolved_evidence", [])
    ))

    try:
        stored = AuditObservationRepository(db).record(
            command,
            idempotency_key=idempotency_key,
        )
    except MissingBin as error:
        return problem.missing_bin_response(str(error))
    except MissingBatch as error:
        return problem.missing_batch_response(str(error))
    except AuditSnapshotStale as error:
        return problem.problem_response(status_code=409, json={
            "type": "audit-snapshot-stale",
            "title": "Inventory changed after this audit snapshot was read.",
            "current_snapshot_token": error.current_snapshot_token,
        })
    except AuditSnapshotBlocked as error:
        return problem.problem_response(status_code=409, json={
            "type": "audit-snapshot-blocked",
            "title": "The current inventory state cannot be audited safely.",
            "blockers": error.blockers,
        })
    except AuditCountsRejected as error:
        return problem.problem_response(status_code=409, json={
            "type": "audit-counts-rejected",
            "title": "The reviewed counts do not match this audit snapshot.",
            "blocker": error.code,
            "detail": error.detail,
        })
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )

    return jsonify({
        "status": "audit observation recorded",
        "state": stored.observation,
    }), 200 if stored.replayed else 201


@audit_observations.route(
    "/api/audit-observations/<observation_id>/reconciliation",
    methods=["POST"],
)
@no_cache
def audit_observation_reconciliation_post(observation_id):
    """Apply one current, complete physical count as an inventory variance."""
    observation_id_error = _observation_id_error(observation_id)
    if observation_id_error is not None:
        return observation_id_error
    idempotency_key, idempotency_error = _idempotency_key_error()
    if idempotency_error is not None:
        return idempotency_error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return problem.invalid_params_response_simple(
            "body",
            "must be a JSON object",
        )
    try:
        disposition = audit_reconciliation_command_schema(body)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)

    repository = InventoryRepository(db)
    try:
        stored = repository.reconcile_audit_observation(
            observation_id,
            disposition,
            idempotency_key=idempotency_key,
        )
    except MissingAuditObservation:
        return problem.missing_resource_response(
            f"/api/audit-observations/{observation_id}"
        )
    except MissingBatch as error:
        return problem.missing_batch_response(str(error))
    except MissingBin as error:
        return problem.missing_bin_response(str(error))
    except InsufficientHolding:
        return problem.problem_response(status_code=409, json={
            "type": "audit-reconciliation-rejected",
            "title": "This audit observation cannot be reconciled now.",
            "blocker": "insufficient-holding",
            "detail": "the recorded inventory is no longer available",
        })
    except AuditReconciliationRejected as error:
        response = {
            "type": "audit-reconciliation-rejected",
            "title": "This audit observation cannot be reconciled now.",
            "blocker": error.code,
            "detail": error.detail,
        }
        response.update(error.context)
        return problem.problem_response(status_code=409, json=response)
    except IdempotencyConflict:
        return problem.duplicate_resource_response(
            "Idempotency-Key",
            "must not be reused for a different request",
        )

    receipt = repository.receipt(stored.result["operation_id"])
    return jsonify({
        "status": "audit observation reconciled",
        "state": receipt,
    }), 200 if stored.replayed else 201
