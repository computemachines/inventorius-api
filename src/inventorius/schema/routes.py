"""API routes for schema management."""

from flask import Blueprint, jsonify, request

from .trigger_engine import (
    Schema,
    TriggerEngine,
    schema_to_dict,
    schema_from_dict,
)
from .sample_schemas import (
    get_electronics_schema,
    get_decimal_schema,
    get_sku_schema,
    get_batch_schema,
)

bp = Blueprint("schema", __name__, url_prefix="/api/schema")

# In-memory schema store (will be MongoDB later)
_schemas: dict[str, Schema] = {}


def _get_schema(name: str) -> Schema | None:
    """Get a schema by name, loading sample if needed."""
    if name not in _schemas:
        if name == "electronics":
            _schemas[name] = get_electronics_schema()
        elif name == "decimal":
            _schemas[name] = get_decimal_schema()
        elif name == "sku":
            _schemas[name] = get_sku_schema()
        elif name == "batch":
            _schemas[name] = get_batch_schema()
    return _schemas.get(name)


@bp.route("/list", methods=["GET"])
def list_schemas():
    """List available schemas."""
    # For now, just return hardcoded list
    return jsonify({
        "schemas": ["sku", "batch", "electronics", "decimal"]
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
