"""Wire-boundary tests for temporary constraint queries."""

from inventorius.constraint_queries import ConstraintQueryEvaluator
from inventorius.constraint_query_codec import (
    query_request_from_document,
    query_result_document,
)


ONE = {"numerator": "1", "denominator": "1"}
ZERO = {"numerator": "0", "denominator": "1"}


def request_document(query, *, overlay=None):
    document = {
        "snapshot": {
            "revision": 7,
            "variables": [
                {
                    "variable_id": "quantity",
                    "unit": "each",
                    "domain": "discrete",
                }
            ],
            "constraints": [
                {
                    "constraint_id": "quantity:upper",
                    "coefficients": {"quantity": ONE},
                    "relation": "at-most",
                    "bound": {"numerator": "10", "denominator": "1"},
                }
            ],
        },
        "query": query,
    }
    if overlay is not None:
        document["overlay"] = overlay
    return document


def evaluate(document):
    snapshot, overlay, query = query_request_from_document(document)
    return query_result_document(
        ConstraintQueryEvaluator().evaluate(snapshot, query, overlay=overlay)
    )


def test_expression_bounds_use_existing_snapshot_and_query_types():
    result = evaluate(request_document({
        "kind": "expression-bounds",
        "expression": {"quantity": ONE},
    }))

    assert result == {
        "kind": "expression-bounds",
        "graph_revision": 7,
        "status": "solved",
        "unit": "each",
        "domain": "discrete",
        "bounds": {
            "minimum": ZERO,
            "maximum": {"numerator": "10", "denominator": "1"},
        },
        "conflict_constraint_ids": [],
    }


def test_overlay_is_temporary_and_supports_counterfactual_queries():
    result = evaluate(request_document(
        {"kind": "counterfactual-feasibility"},
        overlay={
            "variables": [],
            "constraints": [{
                "constraint_id": "hypothetical:too-many",
                "coefficients": {"quantity": ONE},
                "relation": "at-least",
                "bound": {"numerator": "11", "denominator": "1"},
            }],
        },
    ))

    assert result["classification"] == "contradictory"
    assert result["baseline_conflict_constraint_ids"] == []
    assert set(result["augmented_conflict_constraint_ids"]) == {
        "quantity:upper",
        "hypothetical:too-many",
    }


def test_threshold_query_reports_possible_and_guaranteed_separately():
    result = evaluate(request_document({
        "kind": "threshold-predicate",
        "expression": {"quantity": ONE},
        "relation": "at-least",
        "threshold": {"numerator": "5", "denominator": "1"},
    }))

    assert result["possible"] is True
    assert result["guaranteed"] is False
    assert result["bounds"] == {
        "minimum": ZERO,
        "maximum": {"numerator": "10", "denominator": "1"},
    }


def test_request_rejects_fields_outside_the_direct_dataclass_shape():
    document = request_document({
        "kind": "expression-bounds",
        "expression": {"quantity": ONE},
    })
    document["snapshot"]["compatibility_mode"] = True

    try:
        query_request_from_document(document)
    except ValueError as error:
        assert "compatibility_mode" in str(error)
    else:
        raise AssertionError("unexpected fields must fail closed")
