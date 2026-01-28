"""
Unified Trigger Model - Core evaluation engine.

Everything is a mixin. Any field value can trigger additional mixins.
Mixins are scoped - a child mixin can only trigger if its parent is active.
"""

from dataclasses import dataclass, field
from typing import Any
import json


@dataclass
class SchemaField:
    """A field definition within a mixin."""
    name: str
    field_type: str  # "text", "number", "enum", "bool", "unit", "file"
    options: list[str] | None = None  # For enum type, or MIME types for file type
    unit: str | None = None  # For unit type (e.g., "Ω", "ppm/°C")
    required: bool = False


@dataclass
class TriggerCondition:
    """Condition that activates a child mixin."""
    field_name: str
    operator: str  # "in", "eq", "lt", "gt", "lte", "gte", "neq", "set", "and"
    value: Any  # Single value, list for "in", or list of TriggerConditions for "and"

    def evaluate(self, field_values: dict) -> bool:
        """Check if this condition is met by the given field values."""
        # Special case: "and" combines multiple conditions
        if self.operator == "and":
            # value is a list of TriggerCondition objects
            return all(cond.evaluate(field_values) for cond in self.value)

        # Special case: "set" checks if field has a non-empty value
        if self.operator == "set":
            if self.field_name not in field_values:
                return False
            actual = field_values[self.field_name]
            # Check for truthy non-empty value
            return actual is not None and actual != "" and actual != []

        if self.field_name not in field_values:
            return False

        actual = field_values[self.field_name]

        if self.operator == "eq":
            return actual == self.value
        elif self.operator == "neq":
            return actual != self.value
        elif self.operator == "in":
            return actual in self.value
        elif self.operator == "lt":
            return actual < self.value
        elif self.operator == "gt":
            return actual > self.value
        elif self.operator == "lte":
            return actual <= self.value
        elif self.operator == "gte":
            return actual >= self.value
        else:
            raise ValueError(f"Unknown operator: {self.operator}")


@dataclass
class ChildMixin:
    """A child mixin that can be triggered."""
    mixin_name: str
    trigger: TriggerCondition


@dataclass
class Mixin:
    """A mixin definition - adds fields and scopes child mixins."""
    name: str
    fields: list[SchemaField] = field(default_factory=list)
    children: list[ChildMixin] = field(default_factory=list)


@dataclass
class IntersectionRule:
    """Fields added when a specific combination of mixins is active."""
    when: list[str]  # List of mixin names that must all be active
    adds: list[SchemaField] = field(default_factory=list)


@dataclass
class Schema:
    """Complete schema definition."""
    root_mixins: list[str]  # Mixins available at form start
    mixins: dict[str, Mixin]  # All mixin definitions
    intersections: list[IntersectionRule] = field(default_factory=list)


@dataclass
class FormState:
    """Current state of a form being filled out."""
    active_mixins: list[str]
    field_values: dict[str, Any]
    available_fields: list[SchemaField]

    def to_dict(self) -> dict:
        return {
            "active_mixins": self.active_mixins,
            "field_values": self.field_values,
            "available_fields": [f.name for f in self.available_fields],
        }


class TriggerEngine:
    """Evaluates triggers and computes form state."""

    def __init__(self, schema: Schema):
        self.schema = schema

    def evaluate(self, active_mixins: list[str], field_values: dict) -> FormState:
        """
        Compute the complete form state given active mixins and field values.

        Iterates until no new mixins trigger.
        Maintains activation order for consistent field ordering.
        """
        # Use list for order, set for fast lookup
        active_list = list(active_mixins)
        active_set = set(active_mixins)
        fields = []

        changed = True
        iterations = 0
        max_iterations = 100  # Safety limit

        while changed and iterations < max_iterations:
            changed = False
            iterations += 1

            # Collect fields from all active mixins (in activation order)
            fields = []
            for mixin_name in active_list:
                mixin = self.schema.mixins.get(mixin_name)
                if mixin:
                    fields.extend(mixin.fields)

            # Check each active mixin's children (in activation order)
            for mixin_name in active_list:
                mixin = self.schema.mixins.get(mixin_name)
                if not mixin:
                    continue

                for child in mixin.children:
                    if child.mixin_name not in active_set:
                        if child.trigger.evaluate(field_values):
                            active_list.append(child.mixin_name)
                            active_set.add(child.mixin_name)
                            changed = True

            # Check intersection rules
            for rule in self.schema.intersections:
                if all(m in active_set for m in rule.when):
                    # Add intersection fields (avoid duplicates by name)
                    existing_names = {f.name for f in fields}
                    for f in rule.adds:
                        if f.name not in existing_names:
                            fields.append(f)

        return FormState(
            active_mixins=active_list,  # Preserve activation order
            field_values=field_values,
            available_fields=fields,
        )

    def get_root_mixins(self) -> list[str]:
        """Return the list of mixins available at form start."""
        return self.schema.root_mixins


# --- JSON Serialization ---

def schema_field_to_dict(f: SchemaField) -> dict:
    d = {"name": f.name, "type": f.field_type}
    if f.options:
        d["options"] = f.options
    if f.unit:
        d["unit"] = f.unit
    if f.required:
        d["required"] = f.required
    return d


def schema_field_from_dict(d: dict) -> SchemaField:
    return SchemaField(
        name=d["name"],
        field_type=d["type"],
        options=d.get("options"),
        unit=d.get("unit"),
        required=d.get("required", False),
    )


def trigger_to_dict(t: TriggerCondition) -> dict:
    if t.operator == "and":
        # Recursively serialize nested conditions
        return {"field": t.field_name, "op": t.operator, "value": [trigger_to_dict(c) for c in t.value]}
    return {"field": t.field_name, "op": t.operator, "value": t.value}


def trigger_from_dict(d: dict) -> TriggerCondition:
    if d["op"] == "and":
        # Recursively deserialize nested conditions
        return TriggerCondition(
            field_name=d["field"],
            operator=d["op"],
            value=[trigger_from_dict(c) for c in d["value"]],
        )
    return TriggerCondition(
        field_name=d["field"],
        operator=d["op"],
        value=d["value"],
    )


def child_mixin_to_dict(c: ChildMixin) -> dict:
    return {"mixin": c.mixin_name, "trigger": trigger_to_dict(c.trigger)}


def child_mixin_from_dict(d: dict) -> ChildMixin:
    return ChildMixin(
        mixin_name=d["mixin"],
        trigger=trigger_from_dict(d["trigger"]),
    )


def mixin_to_dict(m: Mixin) -> dict:
    return {
        "name": m.name,
        "fields": [schema_field_to_dict(f) for f in m.fields],
        "children": [child_mixin_to_dict(c) for c in m.children],
    }


def mixin_from_dict(d: dict) -> Mixin:
    return Mixin(
        name=d["name"],
        fields=[schema_field_from_dict(f) for f in d.get("fields", [])],
        children=[child_mixin_from_dict(c) for c in d.get("children", [])],
    )


def intersection_to_dict(r: IntersectionRule) -> dict:
    return {
        "when": r.when,
        "adds": [schema_field_to_dict(f) for f in r.adds],
    }


def intersection_from_dict(d: dict) -> IntersectionRule:
    return IntersectionRule(
        when=d["when"],
        adds=[schema_field_from_dict(f) for f in d.get("adds", [])],
    )


def schema_to_dict(s: Schema) -> dict:
    return {
        "root_mixins": s.root_mixins,
        "mixins": {name: mixin_to_dict(m) for name, m in s.mixins.items()},
        "intersections": [intersection_to_dict(r) for r in s.intersections],
    }


def schema_from_dict(d: dict) -> Schema:
    return Schema(
        root_mixins=d["root_mixins"],
        mixins={name: mixin_from_dict(m) for name, m in d["mixins"].items()},
        intersections=[intersection_from_dict(r) for r in d.get("intersections", [])],
    )


def schema_to_json(s: Schema) -> str:
    return json.dumps(schema_to_dict(s), indent=2)


def schema_from_json(j: str) -> Schema:
    return schema_from_dict(json.loads(j))
