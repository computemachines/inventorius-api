"""Tests for the unified trigger model schema system."""

import pytest
from inventorius.schema import (
    SchemaField,
    TriggerCondition,
    ChildMixin,
    Mixin,
    IntersectionRule,
    Schema,
    TriggerEngine,
    schema_to_json,
    schema_from_json,
)


@pytest.fixture
def electronics_schema():
    """Build a test schema for electronic components."""
    resistance = SchemaField("resistance", "unit", unit="Ω")
    tolerance = SchemaField("tolerance", "enum", options=["1%", "5%", "10%"])
    package = SchemaField("package", "enum", options=["0201", "0402", "0603", "DIP", "TO-220"])
    temp_coef = SchemaField("temp_coefficient", "unit", unit="ppm/°C")
    wire_gauge = SchemaField("wire_gauge", "number")
    material = SchemaField("material", "enum", options=["copper", "nichrome"])

    resistor = Mixin(
        name="Resistor",
        fields=[resistance, tolerance],
        children=[ChildMixin("ElectronicPackage", TriggerCondition("resistance", "gte", 0))]
    )

    electronic_package = Mixin(
        name="ElectronicPackage",
        fields=[package],
        children=[
            ChildMixin("SMD", TriggerCondition("package", "in", ["0201", "0402", "0603"])),
            ChildMixin("ThroughHole", TriggerCondition("package", "in", ["DIP", "TO-220"])),
        ]
    )

    smd = Mixin(name="SMD", fields=[], children=[])

    through_hole = Mixin(
        name="ThroughHole",
        fields=[wire_gauge],
        children=[ChildMixin("HighCurrentWire", TriggerCondition("wire_gauge", "lt", 20))]
    )

    high_current = Mixin(name="HighCurrentWire", fields=[material], children=[])

    return Schema(
        root_mixins=["Resistor"],
        mixins={
            "Resistor": resistor,
            "ElectronicPackage": electronic_package,
            "SMD": smd,
            "ThroughHole": through_hole,
            "HighCurrentWire": high_current,
        },
        intersections=[IntersectionRule(when=["Resistor", "SMD"], adds=[temp_coef])],
    )


class TestTriggerCondition:
    def test_eq(self):
        t = TriggerCondition("x", "eq", 5)
        assert t.evaluate({"x": 5}) is True
        assert t.evaluate({"x": 6}) is False
        assert t.evaluate({}) is False

    def test_in(self):
        t = TriggerCondition("x", "in", ["a", "b", "c"])
        assert t.evaluate({"x": "a"}) is True
        assert t.evaluate({"x": "d"}) is False

    def test_lt(self):
        t = TriggerCondition("x", "lt", 10)
        assert t.evaluate({"x": 5}) is True
        assert t.evaluate({"x": 10}) is False
        assert t.evaluate({"x": 15}) is False

    def test_numeric_comparison_accepts_browser_string_values(self):
        t = TriggerCondition("wire_gauge", "lt", 20)
        assert t.evaluate({"wire_gauge": "14"}) is True
        assert t.evaluate({"wire_gauge": "22"}) is False

    def test_invalid_ordered_value_does_not_crash_evaluation(self):
        t = TriggerCondition("wire_gauge", "lt", 20)
        assert t.evaluate({"wire_gauge": "not a number"}) is False

    def test_gte(self):
        t = TriggerCondition("x", "gte", 0)
        assert t.evaluate({"x": 0}) is True
        assert t.evaluate({"x": 100}) is True
        assert t.evaluate({"x": -1}) is False


class TestTriggerEngine:
    def test_basic_evaluation(self, electronics_schema):
        engine = TriggerEngine(electronics_schema)
        state = engine.evaluate(["Resistor"], {"resistance": 10000})

        assert "Resistor" in state.active_mixins
        assert "ElectronicPackage" in state.active_mixins

    def test_smd_trigger(self, electronics_schema):
        engine = TriggerEngine(electronics_schema)
        state = engine.evaluate(["Resistor"], {"resistance": 10000, "package": "0402"})

        assert "SMD" in state.active_mixins
        field_names = [f.name for f in state.available_fields]
        assert "temp_coefficient" in field_names  # intersection rule

    def test_through_hole_trigger(self, electronics_schema):
        engine = TriggerEngine(electronics_schema)
        state = engine.evaluate(["Resistor"], {"resistance": 100, "package": "DIP"})

        assert "ThroughHole" in state.active_mixins
        assert "SMD" not in state.active_mixins

    def test_deep_chain(self, electronics_schema):
        engine = TriggerEngine(electronics_schema)
        state = engine.evaluate(["Resistor"], {
            "resistance": 100,
            "package": "DIP",
            "wire_gauge": 14
        })

        assert "ThroughHole" in state.active_mixins
        assert "HighCurrentWire" in state.active_mixins
        field_names = [f.name for f in state.available_fields]
        assert "material" in field_names

    def test_scoping(self, electronics_schema):
        """Child mixin can't trigger without parent in hierarchy."""
        # Create isolated schema without Resistor->ElectronicPackage link
        isolated = Schema(
            root_mixins=["Resistor"],
            mixins={
                "Resistor": Mixin("Resistor", [SchemaField("resistance", "unit")], []),
                "SMD": electronics_schema.mixins["SMD"],
            },
            intersections=[]
        )
        engine = TriggerEngine(isolated)
        state = engine.evaluate(["Resistor"], {"resistance": 10000, "package": "0402"})

        assert "SMD" not in state.active_mixins


class TestJsonSerialization:
    def test_roundtrip(self, electronics_schema):
        json_str = schema_to_json(electronics_schema)
        restored = schema_from_json(json_str)

        assert restored.root_mixins == electronics_schema.root_mixins
        assert set(restored.mixins.keys()) == set(electronics_schema.mixins.keys())

    def test_behavior_preserved(self, electronics_schema):
        restored = schema_from_json(schema_to_json(electronics_schema))

        engine1 = TriggerEngine(electronics_schema)
        engine2 = TriggerEngine(restored)

        values = {"resistance": 10000, "package": "0402"}
        state1 = engine1.evaluate(["Resistor"], values)
        state2 = engine2.evaluate(["Resistor"], values)

        assert state1.active_mixins == state2.active_mixins


def test_multiline_text_is_preserved_by_schema_roundtrip():
    from inventorius.schema.sample_schemas import get_sku_schema
    from inventorius.schema.trigger_engine import schema_to_dict, schema_from_dict
    definition = schema_to_dict(get_sku_schema())
    assert "Name" in definition["root_mixins"]
    assert definition["mixins"]["Name"]["fields"] == [{"name": "name", "type": "text"}]
    description = definition["mixins"]["Description"]["fields"][0]
    assert description == {"name": "description", "type": "text", "multiline": True}
    assert schema_to_dict(schema_from_dict(definition)) == definition


@pytest.mark.parametrize("default", [True, False])
def test_boolean_default_survives_schema_roundtrip(default):
    from inventorius.schema.trigger_engine import schema_from_dict, schema_to_dict
    field = {"name": "enabled", "type": "bool", "default": default}
    definition = {"root_mixins": ["Root"], "mixins": {
        "Root": {"name": "Root", "fields": [field]},
    }, "intersections": [{"when": ["Root"], "adds": [field]}]}
    saved = schema_to_dict(schema_from_dict(definition))
    assert saved["mixins"]["Root"]["fields"] == [field]
    assert saved["intersections"][0]["adds"] == [field]


def test_legacy_boolean_default_remains_omitted():
    from inventorius.schema.trigger_engine import schema_field_from_dict, schema_field_to_dict
    field = {"name": "enabled", "type": "bool"}
    assert schema_field_to_dict(schema_field_from_dict(field)) == field


@pytest.mark.parametrize("field_type,default", [
    ("bool", "false"), ("bool", 0), ("bool", None), ("text", False),
])
def test_field_default_requires_a_boolean_on_a_bool_field(field_type, default):
    from inventorius.schema.trigger_engine import schema_field_from_dict
    with pytest.raises(ValueError, match="must be true or false"):
        schema_field_from_dict({"name": "enabled", "type": field_type, "default": default})
