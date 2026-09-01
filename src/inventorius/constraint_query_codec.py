"""Direct JSON forms for temporary constraint queries.

This boundary mirrors the persistence-free solver dataclasses. It does not
define a second graph model or a durable storage format.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from inventorius.constraint_queries import (
    ConstraintGraphSnapshot,
    ConstraintOverlay,
    ConstraintQuery,
    ConstraintQueryResult,
    CounterfactualFeasibilityQuery,
    CounterfactualFeasibilityResult,
    ExactLinearExpression,
    ExpressionBoundsQuery,
    ExpressionBoundsResult,
    ThresholdPredicateQuery,
    ThresholdPredicateResult,
)
from inventorius.quantity_codec import (
    rational_document,
    rational_from_document,
)
from inventorius.quantity_constraints import (
    ConstraintRelation,
    LinearConstraint,
    QuantityBounds,
    QuantityDomain,
    QuantityVariable,
)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _list(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _fields(
    value: Mapping[str, object],
    required: set[str],
    field: str,
    *,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unexpected = sorted(set(value) - allowed)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unexpected {unexpected}")
        raise ValueError(f"{field} has invalid fields: {', '.join(details)}")


def _variable(value: object, field: str) -> QuantityVariable:
    document = _mapping(value, field)
    _fields(document, {"variable_id", "unit", "domain"}, field)
    try:
        domain = QuantityDomain(document["domain"])
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field}.domain is unsupported") from error
    return QuantityVariable(
        document["variable_id"],
        document["unit"],
        domain,
    )


def _coefficients(value: object, field: str):
    document = _mapping(value, field)
    return tuple(
        (
            variable_id,
            rational_from_document(coefficient, f"{field}.{variable_id}"),
        )
        for variable_id, coefficient in document.items()
    )


def _constraint(value: object, field: str) -> LinearConstraint:
    document = _mapping(value, field)
    _fields(
        document,
        {"constraint_id", "coefficients", "relation", "bound"},
        field,
    )
    try:
        relation = ConstraintRelation(document["relation"])
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field}.relation is unsupported") from error
    return LinearConstraint(
        document["constraint_id"],
        _coefficients(document["coefficients"], f"{field}.coefficients"),
        relation,
        rational_from_document(document["bound"], f"{field}.bound"),
    )


def _variables(value: object, field: str) -> tuple[QuantityVariable, ...]:
    return tuple(
        _variable(item, f"{field}[{index}]")
        for index, item in enumerate(_list(value, field))
    )


def _constraints(value: object, field: str) -> tuple[LinearConstraint, ...]:
    return tuple(
        _constraint(item, f"{field}[{index}]")
        for index, item in enumerate(_list(value, field))
    )


def _snapshot(value: object) -> ConstraintGraphSnapshot:
    document = _mapping(value, "snapshot")
    _fields(document, {"revision", "variables", "constraints"}, "snapshot")
    return ConstraintGraphSnapshot(
        document["revision"],
        _variables(document["variables"], "snapshot.variables"),
        _constraints(document["constraints"], "snapshot.constraints"),
    )


def _overlay(value: object) -> ConstraintOverlay:
    document = _mapping(value, "overlay")
    _fields(document, {"variables", "constraints"}, "overlay")
    return ConstraintOverlay(
        _variables(document["variables"], "overlay.variables"),
        _constraints(document["constraints"], "overlay.constraints"),
    )


def _expression(value: object, field: str) -> ExactLinearExpression:
    return ExactLinearExpression(dict(_coefficients(value, field)))


def _query(value: object) -> ConstraintQuery:
    document = _mapping(value, "query")
    kind = document.get("kind")
    if kind == "expression-bounds":
        _fields(document, {"kind", "expression"}, "query")
        return ExpressionBoundsQuery(
            _expression(document["expression"], "query.expression")
        )
    if kind == "threshold-predicate":
        _fields(
            document,
            {"kind", "expression", "relation", "threshold"},
            "query",
        )
        try:
            relation = ConstraintRelation(document["relation"])
        except (TypeError, ValueError) as error:
            raise ValueError("query.relation is unsupported") from error
        return ThresholdPredicateQuery(
            _expression(document["expression"], "query.expression"),
            relation,
            rational_from_document(document["threshold"], "query.threshold"),
        )
    if kind == "counterfactual-feasibility":
        _fields(document, {"kind"}, "query")
        return CounterfactualFeasibilityQuery()
    raise ValueError("query.kind is unsupported")


def query_request_from_document(
    value: object,
) -> tuple[ConstraintGraphSnapshot, ConstraintOverlay | None, ConstraintQuery]:
    """Decode one temporary solver request into the existing domain types."""

    document = _mapping(value, "body")
    _fields(document, {"snapshot", "query"}, "body", optional={"overlay"})
    overlay = _overlay(document["overlay"]) if "overlay" in document else None
    return _snapshot(document["snapshot"]), overlay, _query(document["query"])


def _bounds_document(bounds: QuantityBounds | None):
    if bounds is None:
        return None
    return {
        "minimum": (
            rational_document(bounds.minimum) if bounds.minimum is not None else None
        ),
        "maximum": (
            rational_document(bounds.maximum) if bounds.maximum is not None else None
        ),
    }


def query_result_document(result: ConstraintQueryResult) -> dict[str, object]:
    """Encode a structured solver result without exposing the solver adapter."""

    if isinstance(result, ExpressionBoundsResult):
        return {
            "kind": "expression-bounds",
            "graph_revision": result.graph_revision,
            "status": result.status.value,
            "unit": result.unit,
            "domain": result.domain.value,
            "bounds": _bounds_document(result.bounds),
            "conflict_constraint_ids": list(result.conflict_constraint_ids),
        }
    if isinstance(result, ThresholdPredicateResult):
        return {
            "kind": "threshold-predicate",
            "graph_revision": result.graph_revision,
            "status": result.status.value,
            "unit": result.unit,
            "domain": result.domain.value,
            "relation": result.relation.value,
            "threshold": rational_document(result.threshold),
            "bounds": _bounds_document(result.bounds),
            "possible": result.possible,
            "guaranteed": result.guaranteed,
            "conflict_constraint_ids": list(result.conflict_constraint_ids),
        }
    if isinstance(result, CounterfactualFeasibilityResult):
        return {
            "kind": "counterfactual-feasibility",
            "graph_revision": result.graph_revision,
            "classification": result.classification.value,
            "baseline_conflict_constraint_ids": list(
                result.baseline_conflict_constraint_ids
            ),
            "augmented_conflict_constraint_ids": list(
                result.augmented_conflict_constraint_ids
            ),
        }
    raise ValueError("result has an unsupported type")
