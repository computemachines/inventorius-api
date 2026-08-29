"""Typed, query-time evaluation over immutable quantity constraint graphs.

This module is deliberately persistence-free.  A graph snapshot contains only
the variables and named semantic facts needed to reconstruct a fresh
``QuantityConstraintSystem``.  Non-negativity is implicit in each quantity
variable and is therefore neither copied into a snapshot nor accepted in an
overlay as a second kind of fact.

The boundary exposes exact linear expressions and structured answers; Z3 and
the mutable solver adapter remain implementation details of
``quantity_constraints``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Mapping, Sequence

from inventorius.quantity_constraints import (
    ConstraintRelation,
    InfeasibleQuantityFacts,
    LinearConstraint,
    Number,
    QuantityBounds,
    QuantityConstraintSystem,
    QuantityDomain,
    QuantityQueryIndeterminate,
    QuantityVariable,
)


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


def _fraction(value: Number, field: str) -> Fraction:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an exact number")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, (int, str)):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError(f"{field} must be an exact number") from error
    raise ValueError(f"{field} must be an int, decimal string, or Fraction")


def _revision(value: object) -> int:
    """Validate one monotonic graph snapshot identity.

    The integer is version metadata supplied by the graph owner.  Evaluating a
    query does not advance it or otherwise imply any persistence operation.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("revision must be a nonnegative integer")
    return value


def _tuples(
    variables: Sequence[QuantityVariable],
    constraints: Sequence[LinearConstraint],
) -> tuple[tuple[QuantityVariable, ...], tuple[LinearConstraint, ...]]:
    stable_variables = tuple(variables)
    if any(not isinstance(item, QuantityVariable) for item in stable_variables):
        raise ValueError("variables must contain QuantityVariable values")
    stable_constraints = tuple(
        _canonical_constraint(constraint) for constraint in constraints
    )
    return stable_variables, stable_constraints


def _canonical_constraint(constraint: LinearConstraint) -> LinearConstraint:
    """Copy one caller-supplied fact into immutable normalized scalar fields."""

    if not isinstance(constraint, LinearConstraint):
        raise ValueError("constraints must contain LinearConstraint values")
    constraint_id = _nonblank(constraint.constraint_id, "constraint_id")
    if not isinstance(constraint.relation, ConstraintRelation):
        raise ValueError("constraint relation must be a ConstraintRelation")
    try:
        raw_terms = tuple(constraint.coefficients)
    except TypeError as error:
        raise ValueError("constraint coefficients must contain term pairs") from error

    normalized = []
    seen_variable_ids: set[str] = set()
    for raw_term in raw_terms:
        if not isinstance(raw_term, (tuple, list)) or len(raw_term) != 2:
            raise ValueError("constraint coefficients must contain term pairs")
        raw_variable_id, raw_coefficient = raw_term
        variable_id = _nonblank(raw_variable_id, "constraint variable_id")
        if variable_id in seen_variable_ids:
            raise ValueError(
                f"constraint {constraint_id} has duplicate terms"
            )
        seen_variable_ids.add(variable_id)
        coefficient = _fraction(
            raw_coefficient,
            f"{constraint_id}.coefficient[{variable_id}]",
        )
        if coefficient != 0:
            normalized.append((variable_id, coefficient))
    if not normalized:
        raise ValueError("a quantity constraint needs a nonzero term")
    return LinearConstraint(
        constraint_id,
        tuple(sorted(normalized)),
        constraint.relation,
        _fraction(constraint.bound, f"{constraint_id}.bound"),
    )


def _validate_local_structure(
    variables: tuple[QuantityVariable, ...],
    constraints: tuple[LinearConstraint, ...],
) -> None:
    variable_ids = [variable.variable_id for variable in variables]
    if len(set(variable_ids)) != len(variable_ids):
        raise ValueError("quantity variable IDs must be unique")

    constraint_ids = [constraint.constraint_id for constraint in constraints]
    if len(set(constraint_ids)) != len(constraint_ids):
        raise ValueError("quantity constraint IDs must be unique")
    for constraint in constraints:
        _nonblank(constraint.constraint_id, "constraint_id")
        if constraint.constraint_id.startswith("domain:"):
            raise ValueError(
                "domain constraints are implicit and cannot be supplied"
            )
        term_ids = [variable_id for variable_id, _ in constraint.coefficients]
        if len(set(term_ids)) != len(term_ids):
            raise ValueError(
                f"constraint {constraint.constraint_id} has duplicate terms"
            )


@dataclass(frozen=True, init=False)
class ConstraintGraphSnapshot:
    """One immutable, revision-fenced set of quantity facts.

    ``constraints`` contains named semantic facts only.  Each variable's
    implicit non-negativity constraint is recreated by the evaluator.
    """

    revision: int
    variables: tuple[QuantityVariable, ...]
    constraints: tuple[LinearConstraint, ...]

    def __init__(
        self,
        revision: int,
        variables: Sequence[QuantityVariable] = (),
        constraints: Sequence[LinearConstraint] = (),
    ) -> None:
        stable_variables, stable_constraints = _tuples(variables, constraints)
        _validate_local_structure(stable_variables, stable_constraints)
        object.__setattr__(self, "revision", _revision(revision))
        object.__setattr__(self, "variables", stable_variables)
        object.__setattr__(self, "constraints", stable_constraints)

    @classmethod
    def capture(
        cls,
        revision: int,
        system: QuantityConstraintSystem,
    ) -> ConstraintGraphSnapshot:
        """Capture semantic facts from an existing in-memory system."""

        if not isinstance(system, QuantityConstraintSystem):
            raise ValueError("system must be a QuantityConstraintSystem")
        implicit_ids = {
            f"domain:{variable.variable_id}:nonnegative"
            for variable in system.variables
        }
        constraints = tuple(
            constraint
            for constraint in system.constraints
            if constraint.constraint_id not in implicit_ids
        )
        return cls(revision, system.variables, constraints)


@dataclass(frozen=True, init=False)
class ConstraintOverlay:
    """Temporary variables and facts evaluated without changing a snapshot."""

    variables: tuple[QuantityVariable, ...]
    constraints: tuple[LinearConstraint, ...]

    def __init__(
        self,
        variables: Sequence[QuantityVariable] = (),
        constraints: Sequence[LinearConstraint] = (),
    ) -> None:
        stable_variables, stable_constraints = _tuples(variables, constraints)
        _validate_local_structure(stable_variables, stable_constraints)
        object.__setattr__(self, "variables", stable_variables)
        object.__setattr__(self, "constraints", stable_constraints)


@dataclass(frozen=True, init=False)
class ExactLinearExpression:
    """An immutable exact linear expression over named quantity variables."""

    coefficients: tuple[tuple[str, Fraction], ...]

    def __init__(self, coefficients: Mapping[str, Number]) -> None:
        if not isinstance(coefficients, Mapping):
            raise ValueError("coefficients must be a mapping")
        normalized = []
        for variable_id, raw_coefficient in coefficients.items():
            stable_id = _nonblank(variable_id, "variable_id")
            coefficient = _fraction(
                raw_coefficient,
                f"coefficient[{stable_id}]",
            )
            if coefficient != 0:
                normalized.append((stable_id, coefficient))
        if not normalized:
            raise ValueError("a quantity expression needs a nonzero term")
        object.__setattr__(self, "coefficients", tuple(sorted(normalized)))

    def as_mapping(self) -> dict[str, Fraction]:
        """Return a disposable mapping for the mutable solver adapter."""

        return dict(self.coefficients)


@dataclass(frozen=True)
class ExpressionBoundsQuery:
    """Find the sharp minimum and maximum of one expression."""

    expression: ExactLinearExpression

    def __post_init__(self) -> None:
        if not isinstance(self.expression, ExactLinearExpression):
            raise ValueError("expression must be an ExactLinearExpression")


@dataclass(frozen=True, init=False)
class ThresholdPredicateQuery:
    """Ask whether an exact threshold is possible and guaranteed."""

    expression: ExactLinearExpression
    relation: ConstraintRelation
    threshold: Fraction

    def __init__(
        self,
        expression: ExactLinearExpression,
        relation: ConstraintRelation,
        threshold: Number,
    ) -> None:
        if not isinstance(expression, ExactLinearExpression):
            raise ValueError("expression must be an ExactLinearExpression")
        if not isinstance(relation, ConstraintRelation) or relation not in (
            ConstraintRelation.AT_LEAST,
            ConstraintRelation.AT_MOST,
        ):
            raise ValueError("threshold relation must be AT_LEAST or AT_MOST")
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "threshold", _fraction(threshold, "threshold"))


@dataclass(frozen=True)
class CounterfactualFeasibilityQuery:
    """Classify whether a temporary overlay introduces inconsistency."""


class QueryStatus(str, Enum):
    """Outcome of an expression query."""

    SOLVED = "solved"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class CounterfactualClassification(str, Enum):
    """Outcome of comparing a base graph with a temporary overlay."""

    BASELINE_CONFLICTED = "baseline-conflicted"
    CONSISTENT = "consistent"
    CONTRADICTORY = "contradictory"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ExpressionBoundsResult:
    """Structured sharp bounds, conflict, or bounded-policy failure."""

    graph_revision: int
    unit: str
    domain: QuantityDomain
    status: QueryStatus
    bounds: QuantityBounds | None
    conflict_constraint_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThresholdPredicateResult:
    """Bounds plus existential and universal threshold truth facets."""

    graph_revision: int
    unit: str
    domain: QuantityDomain
    status: QueryStatus
    relation: ConstraintRelation
    threshold: Fraction
    bounds: QuantityBounds | None
    possible: bool | None
    guaranteed: bool | None
    conflict_constraint_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CounterfactualFeasibilityResult:
    """Global feasibility comparison for a base and augmented graph."""

    graph_revision: int
    classification: CounterfactualClassification
    baseline_conflict_constraint_ids: tuple[str, ...] = ()
    augmented_conflict_constraint_ids: tuple[str, ...] = ()


ConstraintQuery = (
    ExpressionBoundsQuery
    | ThresholdPredicateQuery
    | CounterfactualFeasibilityQuery
)
ConstraintQueryResult = (
    ExpressionBoundsResult
    | ThresholdPredicateResult
    | CounterfactualFeasibilityResult
)


class ConstraintQueryEvaluator:
    """Evaluate each query with a newly reconstructed constraint system."""

    def __init__(self, *, timeout_ms: int = 5_000) -> None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            raise ValueError("timeout_ms must be a positive integer")
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        self._timeout_ms = timeout_ms

    def evaluate(
        self,
        snapshot: ConstraintGraphSnapshot,
        query: ConstraintQuery,
        *,
        overlay: ConstraintOverlay | None = None,
    ) -> ConstraintQueryResult:
        """Answer one query against a snapshot and disposable overlay."""

        if not isinstance(snapshot, ConstraintGraphSnapshot):
            raise ValueError("snapshot must be a ConstraintGraphSnapshot")
        selected_overlay = ConstraintOverlay() if overlay is None else overlay
        if not isinstance(selected_overlay, ConstraintOverlay):
            raise ValueError("overlay must be a ConstraintOverlay")

        if isinstance(query, CounterfactualFeasibilityQuery):
            return self._evaluate_counterfactual(snapshot, selected_overlay)
        if isinstance(query, ExpressionBoundsQuery):
            return self._evaluate_bounds(snapshot, selected_overlay, query)
        if isinstance(query, ThresholdPredicateQuery):
            return self._evaluate_threshold(snapshot, selected_overlay, query)
        raise ValueError("query must be a supported constraint query")

    def _evaluate_bounds(
        self,
        snapshot: ConstraintGraphSnapshot,
        overlay: ConstraintOverlay,
        query: ExpressionBoundsQuery,
    ) -> ExpressionBoundsResult:
        system = self._rebuild(snapshot, overlay)
        unit, domain = self._expression_type(system, query.expression)
        try:
            bounds = system.expression_bounds(query.expression.as_mapping())
        except InfeasibleQuantityFacts as error:
            return ExpressionBoundsResult(
                snapshot.revision,
                unit,
                domain,
                QueryStatus.CONFLICT,
                None,
                tuple(error.fact_ids),
            )
        except QuantityQueryIndeterminate:
            return ExpressionBoundsResult(
                snapshot.revision,
                unit,
                domain,
                QueryStatus.INDETERMINATE,
                None,
            )
        return ExpressionBoundsResult(
            snapshot.revision,
            unit,
            domain,
            QueryStatus.SOLVED,
            bounds,
        )

    def _evaluate_threshold(
        self,
        snapshot: ConstraintGraphSnapshot,
        overlay: ConstraintOverlay,
        query: ThresholdPredicateQuery,
    ) -> ThresholdPredicateResult:
        system = self._rebuild(snapshot, overlay)
        unit, domain = self._expression_type(system, query.expression)
        try:
            bounds = system.expression_bounds(query.expression.as_mapping())
        except InfeasibleQuantityFacts as error:
            return ThresholdPredicateResult(
                snapshot.revision,
                unit,
                domain,
                QueryStatus.CONFLICT,
                query.relation,
                query.threshold,
                None,
                None,
                None,
                tuple(error.fact_ids),
            )
        except QuantityQueryIndeterminate:
            return ThresholdPredicateResult(
                snapshot.revision,
                unit,
                domain,
                QueryStatus.INDETERMINATE,
                query.relation,
                query.threshold,
                None,
                None,
                None,
            )

        possible, guaranteed = self._threshold_facets(
            bounds,
            query.relation,
            query.threshold,
        )
        return ThresholdPredicateResult(
            snapshot.revision,
            unit,
            domain,
            QueryStatus.SOLVED,
            query.relation,
            query.threshold,
            bounds,
            possible,
            guaranteed,
        )

    def _evaluate_counterfactual(
        self,
        snapshot: ConstraintGraphSnapshot,
        overlay: ConstraintOverlay,
    ) -> CounterfactualFeasibilityResult:
        # Rebuild both before solving either.  A malformed overlay must fail
        # closed even when the baseline already contains a conflict.
        baseline = self._rebuild(snapshot, ConstraintOverlay())
        augmented = self._rebuild(snapshot, overlay)
        try:
            if not baseline.is_feasible():
                return CounterfactualFeasibilityResult(
                    snapshot.revision,
                    CounterfactualClassification.BASELINE_CONFLICTED,
                    baseline_conflict_constraint_ids=baseline.conflict(),
                )
        except QuantityQueryIndeterminate:
            return CounterfactualFeasibilityResult(
                snapshot.revision,
                CounterfactualClassification.INDETERMINATE,
            )

        try:
            if augmented.is_feasible():
                return CounterfactualFeasibilityResult(
                    snapshot.revision,
                    CounterfactualClassification.CONSISTENT,
                )
            return CounterfactualFeasibilityResult(
                snapshot.revision,
                CounterfactualClassification.CONTRADICTORY,
                augmented_conflict_constraint_ids=augmented.conflict(),
            )
        except QuantityQueryIndeterminate:
            return CounterfactualFeasibilityResult(
                snapshot.revision,
                CounterfactualClassification.INDETERMINATE,
            )

    def _rebuild(
        self,
        snapshot: ConstraintGraphSnapshot,
        overlay: ConstraintOverlay,
    ) -> QuantityConstraintSystem:
        system = QuantityConstraintSystem(timeout_ms=self._timeout_ms)
        for variable in snapshot.variables:
            system.add_variable(variable)
        for constraint in snapshot.constraints:
            self._add_constraint(system, constraint)
        for variable in overlay.variables:
            system.add_variable(variable)
        for constraint in overlay.constraints:
            self._add_constraint(system, constraint)
        return system

    @staticmethod
    def _add_constraint(
        system: QuantityConstraintSystem,
        constraint: LinearConstraint,
    ) -> None:
        system.add_constraint(
            constraint.constraint_id,
            dict(constraint.coefficients),
            constraint.relation,
            constraint.bound,
        )

    @staticmethod
    def _expression_type(
        system: QuantityConstraintSystem,
        expression: ExactLinearExpression,
    ) -> tuple[str, QuantityDomain]:
        variables = {
            variable.variable_id: variable for variable in system.variables
        }
        units = set()
        domains = set()
        for variable_id, coefficient in expression.coefficients:
            variable = variables.get(variable_id)
            if variable is None:
                raise ValueError(f"unknown quantity variable: {variable_id}")
            units.add(variable.unit)
            domains.add(variable.domain)
        if len(units) != 1:
            raise ValueError("a quantity expression cannot mix units")
        domain = (
            QuantityDomain.DISCRETE
            if domains == {QuantityDomain.DISCRETE}
            and all(
                coefficient.denominator == 1
                for _, coefficient in expression.coefficients
            )
            else QuantityDomain.CONTINUOUS
        )
        return units.pop(), domain

    @staticmethod
    def _threshold_facets(
        bounds: QuantityBounds,
        relation: ConstraintRelation,
        threshold: Fraction,
    ) -> tuple[bool, bool]:
        if relation == ConstraintRelation.AT_LEAST:
            possible = bounds.maximum is None or bounds.maximum >= threshold
            guaranteed = bounds.minimum is not None and bounds.minimum >= threshold
            return possible, guaranteed
        possible = bounds.minimum is None or bounds.minimum <= threshold
        guaranteed = bounds.maximum is not None and bounds.maximum <= threshold
        return possible, guaranteed
