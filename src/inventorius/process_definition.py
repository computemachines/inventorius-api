"""Versioned process-definition CRUD for manufacturing workflows."""

from datetime import datetime, timezone
import re

from flask import Blueprint, jsonify, request, url_for
from pymongo.errors import DuplicateKeyError
from voluptuous.error import MultipleInvalid

from inventorius.db import db
from inventorius.auth import current_actor, require_capability
from inventorius.mutation_receipts import record_mutation
from inventorius.resource_models import ProcessDefinitionEndpoint
from inventorius.util import (
    IdentifierSpaceExhausted,
    admin_get_next,
    admin_increment_code,
    no_cache,
)
from inventorius.validation import (
    process_definition_create_schema,
    process_definition_patch_schema,
    validate_url_id,
)
import inventorius.resource_operations as operations
import inventorius.util_error_responses as problem


process_definition = Blueprint("process_definition", __name__)

CONTENT_FIELDS = (
    "name",
    "kind",
    "description",
    "inputs",
    "outputs",
    "instructions",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _current_revision(document):
    if not document or not document.get("revisions"):
        return None
    return document["revisions"][-1]


def _state(document, revision=None):
    revisions = document.get("revisions", [])
    selected = None
    if revision is None:
        selected = _current_revision(document)
    else:
        selected = next(
            (item for item in revisions if item["revision"] == revision),
            None,
        )
    if selected is None:
        return None

    return {
        "id": document["_id"],
        **{field: selected.get(field) for field in CONTENT_FIELDS},
        "revision": selected["revision"],
        "created_at": document["created_at"],
        "updated_at": selected["created_at"],
        "is_current": selected["revision"] == document["current_revision"],
    }


def _body_or_problem(schema):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, problem.invalid_params_response_simple(
            "body", "must be a JSON object"
        )
    try:
        return schema(body), None
    except MultipleInvalid as error:
        return None, problem.invalid_params_response(error)


def _missing_response(id):
    return problem.missing_resource_response(
        url_for("process_definition.process_definition_get", id=id),
        operations.process_definition_create(),
    )


def _validate_sku_references(content):
    for group in ("inputs", "outputs"):
        for index, requirement in enumerate(content[group]):
            sku_id = requirement.get("sku_id")
            if sku_id and db.sku.find_one({"_id": sku_id}) is None:
                return problem.invalid_params_response_simple(
                    group,
                    f"row {index + 1} references missing SKU {sku_id}",
                )
    return None


@process_definition.route("/api/process-definitions", methods=["GET"])
@no_cache
def process_definitions_get():
    query = request.args.get("query", "").strip()
    matcher = re.compile(re.escape(query), re.IGNORECASE) if query else None
    states = []
    for document in db.process_definition.find():
        state = _state(document)
        if state is None:
            continue
        if matcher and not (
            matcher.search(state["id"])
            or matcher.search(state["name"])
            or matcher.search(state.get("description") or "")
        ):
            continue
        states.append(state)
    states.sort(key=lambda state: (state["name"].casefold(), state["id"]))
    return jsonify({
        "Id": url_for("process_definition.process_definitions_get"),
        "state": states,
        "operations": [operations.process_definition_create()],
    })


@process_definition.route("/api/process-definitions", methods=["POST"])
@require_capability("catalog.mutate")
@no_cache
def process_definitions_post():
    content, error_response = _body_or_problem(process_definition_create_schema)
    if error_response is not None:
        return error_response

    reference_error = _validate_sku_references(content)
    if reference_error is not None:
        return reference_error

    try:
        process_id = admin_get_next("PRC")
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)
    timestamp = _now()
    revision = {
        **content,
        "description": content.get("description", ""),
        "instructions": content.get("instructions", []),
        "revision": 1,
        "created_at": timestamp,
        "actor": current_actor().durable_ref(),
    }
    document = {
        "_id": process_id,
        "current_revision": 1,
        "created_at": timestamp,
        "created_by": current_actor().durable_ref(),
        "revisions": [revision],
    }

    # Burn generated identifiers rather than ever reusing one after a failure.
    admin_increment_code("PRC", process_id)
    try:
        db.process_definition.insert_one(document)
    except DuplicateKeyError:
        return problem.duplicate_resource_response("id")
    record_mutation(
        db, kind="process-definition.create", target=process_id,
        actor=current_actor().durable_ref(),
    )

    return ProcessDefinitionEndpoint.from_state(
        _state(document)
    ).created_success_response()


@process_definition.route("/api/process-definition/<id>", methods=["GET"])
@validate_url_id("PRC")
@no_cache
def process_definition_get(id):
    document = db.process_definition.find_one({"_id": id})
    if document is None:
        return _missing_response(id)

    revision_text = request.args.get("revision")
    revision = None
    if revision_text is not None:
        try:
            revision = int(revision_text)
        except ValueError:
            return problem.invalid_params_response_simple(
                "revision", "must be an integer"
            )
        if revision < 1:
            return problem.invalid_params_response_simple(
                "revision", "must be at least 1"
            )

    state = _state(document, revision)
    if state is None:
        return problem.missing_resource_response(
            f"{url_for('process_definition.process_definition_get', id=id)}"
            f"?revision={revision}"
        )
    return ProcessDefinitionEndpoint.from_state(
        state,
        mutable=state["is_current"],
    ).get_response()


@process_definition.route(
    "/api/process-definition/<id>/revisions",
    methods=["GET"],
)
@validate_url_id("PRC")
@no_cache
def process_definition_revisions_get(id):
    document = db.process_definition.find_one({"_id": id})
    if document is None:
        return _missing_response(id)
    return jsonify({
        "Id": url_for(
            "process_definition.process_definition_revisions_get",
            id=id,
        ),
        "state": [
            _state(document, revision["revision"])
            for revision in reversed(document["revisions"])
        ],
    })


@process_definition.route("/api/process-definition/<id>", methods=["PATCH"])
@validate_url_id("PRC")
@require_capability("catalog.mutate")
@no_cache
def process_definition_patch(id):
    patch, error_response = _body_or_problem(process_definition_patch_schema)
    if error_response is not None:
        return error_response
    if not patch:
        return problem.invalid_params_response_simple(
            "body", "must contain at least one change"
        )

    document = db.process_definition.find_one({"_id": id})
    if document is None:
        return _missing_response(id)

    current = _current_revision(document)
    merged = {
        field: patch.get(field, current.get(field))
        for field in CONTENT_FIELDS
    }
    try:
        content = process_definition_create_schema(merged)
    except MultipleInvalid as error:
        return problem.invalid_params_response(error)

    reference_error = _validate_sku_references(content)
    if reference_error is not None:
        return reference_error

    comparable_current = {field: current.get(field) for field in CONTENT_FIELDS}
    normalized_content = {
        **content,
        "description": content.get("description", ""),
        "instructions": content.get("instructions", []),
    }
    if comparable_current == normalized_content:
        return ProcessDefinitionEndpoint.from_state(
            _state(document)
        ).updated_success_response()

    revision_number = document["current_revision"] + 1
    new_revision = {
        **normalized_content,
        "revision": revision_number,
        "created_at": _now(),
        "actor": current_actor().durable_ref(),
    }
    result = db.process_definition.update_one(
        {"_id": id, "current_revision": document["current_revision"]},
        {
            "$push": {"revisions": new_revision},
            "$set": {"current_revision": revision_number},
        },
    )
    if result.modified_count != 1:
        return problem.problem_response(status_code=409, json={
            "type": "edit-conflict",
            "title": "The process definition changed. Reload it and try again.",
        })
    record_mutation(
        db, kind="process-definition.update", target=id,
        actor=current_actor().durable_ref(),
    )

    refreshed = db.process_definition.find_one({"_id": id})
    return ProcessDefinitionEndpoint.from_state(
        _state(refreshed)
    ).updated_success_response()


@process_definition.route("/api/process-definition/<id>", methods=["DELETE"])
@validate_url_id("PRC")
@require_capability("catalog.mutate")
@no_cache
def process_definition_delete(id):
    document = db.process_definition.find_one({"_id": id})
    if document is None:
        return _missing_response(id)

    if db.process_run.count_documents({"process_definition_id": id}) > 0:
        return problem.problem_response(status_code=403, json={
            "type": "resource-in-use",
            "title": "A process definition used by a run cannot be deleted.",
        })

    state = _state(document)
    db.process_definition.delete_one({"_id": id})
    record_mutation(
        db, kind="process-definition.delete", target=id,
        actor=current_actor().durable_ref(),
    )
    return ProcessDefinitionEndpoint.from_state(state).deleted_success_response()
