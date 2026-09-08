"""API routes and operator commands for schema management."""

from copy import deepcopy
import re

import click
from flask import Blueprint, jsonify, request

from ..db import db
from ..auth import current_actor, public_unsafe, require_capability
from ..mutation_receipts import record_mutation
from ..edit_preconditions import (
    advertise,
    etag_for_state,
    failed_response,
    matches_if_supplied,
    supplied_if_match,
)
from .trigger_engine import (
    Schema,
    TriggerEngine,
    schema_to_dict,
    schema_field_to_dict,
    schema_from_dict,
)
from .catalog import (
    DEFAULT_SCHEMA_FACTORIES,
    EXAMPLE_SCHEMA_FACTORIES,
    install_schemas,
)
from .repository import (
    BOOTSTRAP_ACTOR,
    SchemaEditConflict,
    SchemaHead,
    SchemaRepository,
)

bp = Blueprint("schema", __name__, url_prefix="/api/schema")


def _repository() -> SchemaRepository:
    return SchemaRepository(db)


def _get_schema(name: str, revision: int | None = None) -> Schema | None:
    """Get the active schema or one exact historical revision."""
    definition = _repository().definition(name, revision=revision)
    if definition is not None:
        return schema_from_dict(definition)
    return None


def _schema_etag(name: str, definition: dict) -> str:
    exposed = schema_to_dict(schema_from_dict(definition))
    return etag_for_state(f"schema:{name}", exposed)


def _save_schema(
    name: str,
    schema: Schema,
    *,
    expected: SchemaHead,
) -> None:
    """Publish a schema revision if its definition changed."""
    publication = _repository().publish(
        name,
        schema_to_dict(schema),
        actor=current_actor().durable_ref(),
        expected=expected,
    )
    if publication.changed:
        record_mutation(
            db,
            kind="schema.save",
            target=name,
            actor=current_actor().durable_ref(),
        )


def _delete_schema(name: str, *, expected: SchemaHead) -> bool:
    """Deactivate a schema without erasing its publication history."""
    changed = _repository().deactivate(name, expected=expected)
    if changed:
        record_mutation(
            db, kind="schema.delete", target=name, actor=current_actor().durable_ref()
        )
    return changed


def _requested_revision():
    revision_text = request.args.get("revision")
    if revision_text is None:
        return None, None
    try:
        revision = int(revision_text)
    except ValueError:
        return None, (jsonify({"error": "revision must be an integer"}), 400)
    if revision < 1:
        return None, (jsonify({"error": "revision must be at least 1"}), 400)
    return revision, None


def _schema_for_read(name: str):
    revision, error_response = _requested_revision()
    if error_response is not None:
        return None, error_response
    return _get_schema(name, revision), None


def _edit_conflict_response(name: str):
    return jsonify({
        "error": f"Schema '{name}' changed. Reload it and try again."
    }), 409


@bp.route("/list", methods=["GET"])
def list_schemas():
    """List available schemas from MongoDB."""
    schema_names = _repository().active_names()
    return jsonify({
        "schemas": schema_names
    })


@bp.route("/<name>", methods=["GET"])
def get_schema(name: str):
    """Get a schema definition by name."""
    schema, error_response = _schema_for_read(name)
    if error_response is not None:
        return error_response
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    definition = schema_to_dict(schema)
    response = jsonify(definition)
    if name in {"sku", "batch"} and request.args.get("revision") is None:
        return advertise(response, _schema_etag(name, definition))
    return response


@bp.route("/<name>/roots", methods=["GET"])
def get_root_mixins(name: str):
    """Get the root mixins for a schema (available at form start)."""
    schema, error_response = _schema_for_read(name)
    if error_response is not None:
        return error_response
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    engine = TriggerEngine(schema)
    roots = engine.get_root_mixins()

    # Return basic info about each root mixin
    result = []
    for mixin_name in roots:
        mixin = schema.mixins.get(mixin_name)
        if mixin:
            result.append({
                "name": mixin.name,
                "field_count": len(mixin.fields),
            })

    return jsonify({"root_mixins": result})


@bp.route("/<name>/evaluate", methods=["POST"])
@public_unsafe
def evaluate_schema(name: str):
    """
    Evaluate the schema with given active mixins and field values.

    Resource forms pass use_schema_roots=true instead of hard-coding roots.
    Existing SKU/batch editors also pass resource_id. Its exact canonical ID
    activates the same-named mixin, if present, without changing shared roots.
    Omitting both options preserves explicit mixin selection for admin previews.

    Request body:
    {
        "active_mixins": ["Resistor"],
        "field_values": {"resistance": 10000, "package": "0402"}
    }

    Response:
    {
        "active_mixins": ["Resistor", "ElectronicPackage", "SMD"],
        "available_fields": [...]
    }
    """
    schema, error_response = _schema_for_read(name)
    if error_response is not None:
        return error_response
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "Request body required"}), 400

    active_mixins = data.get("active_mixins", [])
    field_values = data.get("field_values", {})
    use_schema_roots = data.get("use_schema_roots", False)
    resource_id = data.get("resource_id")
    if (
        not isinstance(active_mixins, list)
        or any(not isinstance(mixin, str) for mixin in active_mixins)
        or not isinstance(field_values, dict)
        or not isinstance(use_schema_roots, bool)
    ):
        return jsonify({"error": "Expected a mixin list, field-value object, and boolean use_schema_roots"}), 400

    # Resource identity is evaluation context, never an editable property or a
    # predicted next ID. Keep this convention separate from shared root storage.
    implicit_roots = []
    if resource_id is not None:
        prefix = {"sku": "SKU", "batch": "BAT"}.get(name)
        if (
            prefix is None
            or not isinstance(resource_id, str)
            or re.fullmatch(prefix + r"[0-9]{6}", resource_id) is None
        ):
            return jsonify({"error": "resource_id must be a canonical ID for this SKU or batch schema"}), 400
        if db[name].find_one({"_id": resource_id}, {"_id": 1}) is None:
            return jsonify({"error": "Resource not found"}), 404
        if resource_id in schema.mixins:
            implicit_roots.append(resource_id)

    roots = schema.root_mixins if use_schema_roots or resource_id is not None else []
    active_mixins = list(dict.fromkeys([*roots, *active_mixins, *implicit_roots]))

    engine = TriggerEngine(schema)
    state = engine.evaluate(active_mixins, field_values)

    fields = [schema_field_to_dict(f) for f in state.available_fields]

    return jsonify({
        "active_mixins": state.active_mixins,
        "root_mixins": schema.root_mixins,
        "implicit_root_mixins": implicit_roots,
        "available_fields": fields,
    })


@bp.route("/<name>", methods=["PUT"])
@require_capability("schema.admin")
def create_or_update_schema(name: str):
    """
    Create or update a schema.

    Request body: Full schema definition (root_mixins, mixins, intersections)
    """
    expected = _repository().head(name)
    conditional = supplied_if_match() is not None
    if conditional and (
        name not in {"sku", "batch"}
        or not expected.active
        or not matches_if_supplied(_schema_etag(name, expected.definition))
    ):
        return failed_response()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    try:
        schema = schema_from_dict(data)
    except Exception as e:
        return jsonify({"error": f"Invalid schema: {str(e)}"}), 400

    try:
        _save_schema(name, schema, expected=expected)
    except SchemaEditConflict:
        if conditional:
            return failed_response()
        return _edit_conflict_response(name)
    return jsonify({"message": f"Schema '{name}' saved", "schema": schema_to_dict(schema)}), 200


@bp.route("/<name>", methods=["DELETE"])
@require_capability("schema.admin")
def delete_schema(name: str):
    """Deactivate a schema while retaining its immutable history."""
    expected = _repository().head(name)
    try:
        changed = _delete_schema(name, expected=expected)
    except SchemaEditConflict:
        return _edit_conflict_response(name)
    if changed:
        return jsonify({"message": f"Schema '{name}' deleted"}), 200
    else:
        return jsonify({"error": f"Schema '{name}' not found"}), 404


@bp.route("/<name>/mixin/<mixin_name>", methods=["PUT"])
@require_capability("schema.admin")
def create_or_update_mixin(name: str, mixin_name: str):
    """
    Add or update a mixin within a schema.

    Request body: Mixin definition (name, fields, children)
    """
    from .trigger_engine import mixin_from_dict, mixin_to_dict

    expected = _repository().head(name)
    if not expected.active:
        return jsonify({"error": f"Schema '{name}' not found"}), 404
    schema = schema_from_dict(deepcopy(expected.definition))

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    # Ensure name matches URL
    data["name"] = mixin_name

    try:
        mixin = mixin_from_dict(data)
    except Exception as e:
        return jsonify({"error": f"Invalid mixin: {str(e)}"}), 400

    schema.mixins[mixin_name] = mixin
    try:
        _save_schema(name, schema, expected=expected)
    except SchemaEditConflict:
        return _edit_conflict_response(name)

    return jsonify({
        "message": f"Mixin '{mixin_name}' saved in schema '{name}'",
        "mixin": mixin_to_dict(mixin)
    }), 200


@bp.route("/<name>/mixin/<mixin_name>", methods=["DELETE"])
@require_capability("schema.admin")
def delete_mixin(name: str, mixin_name: str):
    """Delete a mixin from a schema."""
    expected = _repository().head(name)
    if not expected.active:
        return jsonify({"error": f"Schema '{name}' not found"}), 404
    schema = schema_from_dict(deepcopy(expected.definition))

    if mixin_name not in schema.mixins:
        return jsonify({"error": f"Mixin '{mixin_name}' not found in schema '{name}'"}), 404

    # Check if it's a root mixin
    if mixin_name in schema.root_mixins:
        schema.root_mixins.remove(mixin_name)

    del schema.mixins[mixin_name]
    try:
        _save_schema(name, schema, expected=expected)
    except SchemaEditConflict:
        return _edit_conflict_response(name)

    return jsonify({"message": f"Mixin '{mixin_name}' deleted from schema '{name}'"}), 200


@bp.route("/<name>/root/<mixin_name>", methods=["PUT"])
@require_capability("schema.admin")
def add_root_mixin(name: str, mixin_name: str):
    """Add a mixin to the root_mixins list."""
    expected = _repository().head(name)
    if not expected.active:
        return jsonify({"error": f"Schema '{name}' not found"}), 404
    schema = schema_from_dict(deepcopy(expected.definition))

    if mixin_name not in schema.mixins:
        return jsonify({"error": f"Mixin '{mixin_name}' does not exist in schema"}), 400

    if mixin_name not in schema.root_mixins:
        schema.root_mixins.append(mixin_name)
        try:
            _save_schema(name, schema, expected=expected)
        except SchemaEditConflict:
            return _edit_conflict_response(name)

    return jsonify({
        "message": f"'{mixin_name}' added to root_mixins",
        "root_mixins": schema.root_mixins
    }), 200


@bp.route("/<name>/root/<mixin_name>", methods=["DELETE"])
@require_capability("schema.admin")
def remove_root_mixin(name: str, mixin_name: str):
    """Remove a mixin from the root_mixins list."""
    expected = _repository().head(name)
    if not expected.active:
        return jsonify({"error": f"Schema '{name}' not found"}), 404
    schema = schema_from_dict(deepcopy(expected.definition))

    if mixin_name in schema.root_mixins:
        schema.root_mixins.remove(mixin_name)
        try:
            _save_schema(name, schema, expected=expected)
        except SchemaEditConflict:
            return _edit_conflict_response(name)
        return jsonify({
            "message": f"'{mixin_name}' removed from root_mixins",
            "root_mixins": schema.root_mixins
        }), 200
    else:
        return jsonify({"error": f"'{mixin_name}' is not a root mixin"}), 404


@bp.route("/<name>/search", methods=["GET"])
def search_bundles(name: str):
    """
    Search for child mixins (bundles) that can be triggered by a field.

    Query params:
    - field: The trigger field name (e.g., "item_type", "source")
    - q: Search query (prefix match on mixin name, case-insensitive)
    - value: Exact trigger value match (for dropdown selections like package)
    - active: Comma-separated list of currently active mixin IDs (for intersection computation)

    When 'value' is provided, returns bundles whose trigger matches that exact value.
    When 'q' is provided, returns bundles whose name starts with the query.

    Response:
    {
        "bundles": [
            {"id": "Resistor", "name": "Resistor", "fields": [...]},
            ...
        ],
        "intersection_fields": [...]
    }
    """
    from .trigger_engine import schema_field_to_dict

    schema, error_response = _schema_for_read(name)
    if error_response is not None:
        return error_response
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    field_name = request.args.get("field", "")
    query = request.args.get("q", "").lower()
    exact_value = request.args.get("value", "")
    active_param = request.args.get("active", "")
    active_mixins = [m.strip() for m in active_param.split(",") if m.strip()]

    if not field_name:
        return jsonify({"error": "field parameter required"}), 400

    # Find all mixins that have children triggered by this field
    matching_bundles = []

    for mixin_name, mixin in schema.mixins.items():
        for child in mixin.children:
            # Check if this child is triggered by the target field
            if child.trigger.field_name == field_name:
                child_mixin = schema.mixins.get(child.mixin_name)
                if child_mixin:
                    # Apply filters based on search mode
                    matches = False

                    if exact_value:
                        # Exact trigger value match mode
                        trigger_val = child.trigger.value
                        if child.trigger.operator == "eq":
                            matches = trigger_val == exact_value
                        elif child.trigger.operator == "in":
                            matches = exact_value in (trigger_val if isinstance(trigger_val, list) else [trigger_val])
                        # Other operators could be added as needed
                    elif query:
                        # Prefix match on mixin name
                        matches = child_mixin.name.lower().startswith(query)
                    else:
                        # No filter - return all
                        matches = True

                    if matches:
                        # Convert to bundle format
                        bundle = {
                            "id": child_mixin.name,
                            "name": child_mixin.name,
                            "fields": [schema_field_to_dict(f) for f in child_mixin.fields],
                        }
                        # Avoid duplicates (same mixin can be referenced by multiple parents)
                        if not any(b["id"] == bundle["id"] for b in matching_bundles):
                            matching_bundles.append(bundle)

    # Compute intersection fields if active mixins provided
    intersection_fields = []
    if active_mixins and matching_bundles:
        active_set = set(active_mixins)
        for rule in schema.intersections:
            # Check if adding any of the matching bundles would trigger this intersection
            for bundle in matching_bundles:
                test_set = active_set | {bundle["id"]}
                if all(m in test_set for m in rule.when):
                    for f in rule.adds:
                        field_dict = schema_field_to_dict(f)
                        if field_dict not in intersection_fields:
                            intersection_fields.append(field_dict)

    return jsonify({
        "bundles": matching_bundles,
        "intersection_fields": intersection_fields,
    })


@bp.route("/seed", methods=["POST"])
@require_capability("schema.admin")
def seed_schemas():
    """
    Seed the database with sample schemas.

    Use force=true query param to overwrite existing schemas.
    """
    force = request.args.get("force", "false").lower() == "true"
    factories = {**DEFAULT_SCHEMA_FACTORIES, **EXAMPLE_SCHEMA_FACTORIES}
    result = install_schemas(
        db.schema,
        factories,
        force=force,
        actor=current_actor().durable_ref(),
    )
    record_mutation(
        db,
        kind="schema.seed",
        target="catalog",
        actor=current_actor().durable_ref(),
    )

    return jsonify({
        "message": "Seeding complete",
        "seeded": result.installed,
        "skipped": result.skipped,
    }), 200


@bp.cli.command("bootstrap")
@click.option(
    "--force",
    is_flag=True,
    help="Replace existing SKU and Batch schemas with the built-in versions.",
)
@click.option(
    "--include-examples",
    is_flag=True,
    help="Also install the electronics and decimal demonstration schemas.",
)
def bootstrap_schemas(force: bool, include_examples: bool) -> None:
    """Install the schemas required by the SKU and Batch forms."""
    factories = dict(DEFAULT_SCHEMA_FACTORIES)
    if include_examples:
        factories.update(EXAMPLE_SCHEMA_FACTORIES)

    result = install_schemas(
        db.schema,
        factories,
        force=force,
        actor=BOOTSTRAP_ACTOR,
    )
    click.echo(f"Installed: {', '.join(result.installed) or 'none'}")
    click.echo(f"Preserved: {', '.join(result.skipped) or 'none'}")
