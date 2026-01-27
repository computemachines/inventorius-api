"""API routes for schema management."""

from flask import Blueprint, jsonify, request

from ..db import db
from .trigger_engine import (
    Schema,
    TriggerEngine,
    schema_to_dict,
    schema_from_dict,
)

bp = Blueprint("schema", __name__, url_prefix="/api/schema")


def _get_schema(name: str) -> Schema | None:
    """Get a schema by name from MongoDB."""
    doc = db.schema.find_one({"_id": name})
    if doc:
        # Remove MongoDB _id before converting
        schema_dict = {k: v for k, v in doc.items() if k != "_id"}
        return schema_from_dict(schema_dict)
    return None


def _save_schema(name: str, schema: Schema) -> None:
    """Save a schema to MongoDB."""
    doc = schema_to_dict(schema)
    doc["_id"] = name
    db.schema.replace_one({"_id": name}, doc, upsert=True)


def _delete_schema(name: str) -> bool:
    """Delete a schema from MongoDB."""
    result = db.schema.delete_one({"_id": name})
    return result.deleted_count > 0


@bp.route("/list", methods=["GET"])
def list_schemas():
    """List available schemas from MongoDB."""
    schema_docs = db.schema.find({}, {"_id": 1})
    schema_names = [doc["_id"] for doc in schema_docs]
    return jsonify({
        "schemas": schema_names
    })


@bp.route("/<name>", methods=["GET"])
def get_schema(name: str):
    """Get a schema definition by name."""
    schema = _get_schema(name)
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    return jsonify(schema_to_dict(schema))


@bp.route("/<name>/roots", methods=["GET"])
def get_root_mixins(name: str):
    """Get the root mixins for a schema (available at form start)."""
    schema = _get_schema(name)
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
def evaluate_schema(name: str):
    """
    Evaluate the schema with given active mixins and field values.

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
    schema = _get_schema(name)
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    active_mixins = data.get("active_mixins", [])
    field_values = data.get("field_values", {})

    engine = TriggerEngine(schema)
    state = engine.evaluate(active_mixins, field_values)

    # Build response with full field info
    fields = []
    for f in state.available_fields:
        field_info = {
            "name": f.name,
            "type": f.field_type,
        }
        if f.options:
            field_info["options"] = f.options
        if f.unit:
            field_info["unit"] = f.unit
        if f.required:
            field_info["required"] = f.required
        fields.append(field_info)

    return jsonify({
        "active_mixins": state.active_mixins,
        "available_fields": fields,
    })


@bp.route("/<name>", methods=["PUT"])
def create_or_update_schema(name: str):
    """
    Create or update a schema.

    Request body: Full schema definition (root_mixins, mixins, intersections)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    try:
        schema = schema_from_dict(data)
    except Exception as e:
        return jsonify({"error": f"Invalid schema: {str(e)}"}), 400

    _save_schema(name, schema)
    return jsonify({"message": f"Schema '{name}' saved", "schema": schema_to_dict(schema)}), 200


@bp.route("/<name>", methods=["DELETE"])
def delete_schema(name: str):
    """Delete a schema by name."""
    if _delete_schema(name):
        return jsonify({"message": f"Schema '{name}' deleted"}), 200
    else:
        return jsonify({"error": f"Schema '{name}' not found"}), 404


@bp.route("/<name>/mixin/<mixin_name>", methods=["PUT"])
def create_or_update_mixin(name: str, mixin_name: str):
    """
    Add or update a mixin within a schema.

    Request body: Mixin definition (name, fields, children)
    """
    from .trigger_engine import mixin_from_dict, mixin_to_dict

    schema = _get_schema(name)
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

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
    _save_schema(name, schema)

    return jsonify({
        "message": f"Mixin '{mixin_name}' saved in schema '{name}'",
        "mixin": mixin_to_dict(mixin)
    }), 200


@bp.route("/<name>/mixin/<mixin_name>", methods=["DELETE"])
def delete_mixin(name: str, mixin_name: str):
    """Delete a mixin from a schema."""
    schema = _get_schema(name)
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    if mixin_name not in schema.mixins:
        return jsonify({"error": f"Mixin '{mixin_name}' not found in schema '{name}'"}), 404

    # Check if it's a root mixin
    if mixin_name in schema.root_mixins:
        schema.root_mixins.remove(mixin_name)

    del schema.mixins[mixin_name]
    _save_schema(name, schema)

    return jsonify({"message": f"Mixin '{mixin_name}' deleted from schema '{name}'"}), 200


@bp.route("/<name>/root/<mixin_name>", methods=["PUT"])
def add_root_mixin(name: str, mixin_name: str):
    """Add a mixin to the root_mixins list."""
    schema = _get_schema(name)
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    if mixin_name not in schema.mixins:
        return jsonify({"error": f"Mixin '{mixin_name}' does not exist in schema"}), 400

    if mixin_name not in schema.root_mixins:
        schema.root_mixins.append(mixin_name)
        _save_schema(name, schema)

    return jsonify({
        "message": f"'{mixin_name}' added to root_mixins",
        "root_mixins": schema.root_mixins
    }), 200


@bp.route("/<name>/root/<mixin_name>", methods=["DELETE"])
def remove_root_mixin(name: str, mixin_name: str):
    """Remove a mixin from the root_mixins list."""
    schema = _get_schema(name)
    if not schema:
        return jsonify({"error": f"Schema '{name}' not found"}), 404

    if mixin_name in schema.root_mixins:
        schema.root_mixins.remove(mixin_name)
        _save_schema(name, schema)
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

    schema = _get_schema(name)
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
def seed_schemas():
    """
    Seed the database with sample schemas.

    Use force=true query param to overwrite existing schemas.
    """
    from .sample_schemas import (
        get_sku_schema,
        get_batch_schema,
        get_electronics_schema,
        get_decimal_schema,
    )

    force = request.args.get("force", "false").lower() == "true"

    sample_schemas = {
        "sku": get_sku_schema(),
        "batch": get_batch_schema(),
        "electronics": get_electronics_schema(),
        "decimal": get_decimal_schema(),
    }

    seeded = []
    skipped = []

    for name, schema in sample_schemas.items():
        existing = _get_schema(name)
        if existing and not force:
            skipped.append(name)
        else:
            _save_schema(name, schema)
            seeded.append(name)

    return jsonify({
        "message": "Seeding complete",
        "seeded": seeded,
        "skipped": skipped,
    }), 200
