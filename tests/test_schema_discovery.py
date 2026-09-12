from inventorius.schema.discovery import discover_mixins


def definition():
    return {"root_mixins": ["Type"], "mixins": {
        "Type": {"name": "Type", "fields": [], "children": [{"mixin": "Motor", "trigger": {"field": "kind", "op": "eq", "value": "Stepper Motor"}}]},
        "Motor": {"name": "Motor", "fields": [{"name": "Dual shaft", "type": "bool", "default": False}], "children": [{"mixin": "Stepper", "trigger": {"field": "", "op": "and", "value": []}}]},
        "Stepper": {"name": "Stepper", "fields": [{"name": "Phase current", "type": "unit", "unit": "A"}], "children": []},
    }, "intersections": [{"when": ["Motor", "Stepper"], "adds": [{"name": "Torque", "type": "number"}]}]}


def test_discovery_finds_fields_and_explains_cascading_activation():
    result = discover_mixins(definition(), query="phase current")
    assert result["total"] == 1
    selected = result["matches"][0]
    assert selected["name"] == "Stepper"
    assert selected["activation"]["paths"][0]["root"] == "Type"
    assert [step["child"] for step in selected["activation"]["paths"][0]["steps"]] == ["Motor", "Stepper"]
    assert selected["intersections"][0]["adds"][0]["name"] == "Torque"


def test_exact_selection_pagination_and_cycles_are_explicit():
    result = discover_mixins(definition(), names=["Motor", "Missing"])
    assert result["missing_names"] == ["Missing"]
    assert result["matches"][0]["definition"]["fields"][0]["default"] is False
    assert discover_mixins(definition(), limit=1)["has_more"]
    cyclic = definition()
    cyclic["mixins"]["Stepper"]["children"] = [{"mixin": "Motor", "trigger": {"field": "", "op": "and", "value": []}}]
    assert discover_mixins(cyclic, names=["Motor"])["matches"][0]["activation"]["truncated"]
