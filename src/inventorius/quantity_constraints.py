"""Constraint-native quantities for uncertain physical inventory.

This persistence-free module retains observations and operation equations, then
derives bounds when queried. A displayed interval is therefore a projection,
not a pair of independently mutable holding fields. The domain objects remain
solver-neutral; Z3 is only the exact query adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from time import monotonic
from typing import Mapping, Sequence

import z3

from inventorius.ledger import HoldingKey


Number = Fraction | int | str


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


def _fraction(value: Number, field: str) -> Fraction:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an exact number")
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError(f"{field} must be an exact number") from error
    else:
        raise ValueError(f"{field} must be an int, decimal string, or Fraction")
    return result


def _positive_fraction(value: Number, field: str) -> Fraction:
    result = _fraction(value, field)
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


class QuantityDomain(str, Enum):
    """Whether a quantity may be fractional in its declared unit."""

    DISCRETE = "discrete"
    CONTINUOUS = "continuous"


class ConstraintRelation(str, Enum):
    """Supported linear fact relations."""

    EQUAL = "equal"
    AT_LEAST = "at-least"
    AT_MOST = "at-most"


class ObservationBasis(str, Enum):
    """How an operator obtained a quantity claim."""

    COUNTED = "counted"
    MEASURED = "measured"
    ESTIMATED = "estimated"
    CALCULATED = "calculated"


@dataclass(frozen=True)
class QuantityVariable:
    """One nonnegative quantity in one exact unit."""

    variable_id: str
    unit: str
    domain: QuantityDomain

    def __post_init__(self) -> None:
        _nonblank(self.variable_id, "variable_id")
        _nonblank(self.unit, "unit")
        if not isinstance(self.domain, QuantityDomain):
            raise ValueError("domain must be a QuantityDomain")


@dataclass(frozen=True)
class LinearConstraint:
    """One named equation or inequality over compatible quantities."""

    constraint_id: str
    coefficients: tuple[tuple[str, Fraction], ...]
    relation: ConstraintRelation
    bound: Fraction


@dataclass(frozen=True)
class QuantityBounds:
    """Sharp feasible bounds; ``None`` denotes an unbounded side."""

    minimum: Fraction | None
    maximum: Fraction | None
    unit: str
    domain: QuantityDomain

    @property
    def exact(self) -> bool:
        return self.minimum is not None and self.minimum == self.maximum


@dataclass(frozen=True)
class BoundExplanation:
    """Bounds plus deletion-minimal facts and feasible witness histories."""

    bounds: QuantityBounds
    minimum_fact_ids: tuple[str, ...]
    maximum_fact_ids: tuple[str, ...]
    minimum_witness: tuple[tuple[str, Fraction], ...]
    maximum_witness: tuple[tuple[str, Fraction], ...]


class InfeasibleQuantityFacts(ValueError):
    """The retained facts have no jointly feasible physical history."""

    def __init__(self, fact_ids: Sequence[str]):
        self.fact_ids = tuple(fact_ids)
        details = ", ".join(self.fact_ids) or "unknown facts"
        super().__init__(f"quantity facts are inconsistent: {details}")


class QuantityQueryIndeterminate(RuntimeError):
    """The bounded solver policy could not determine an exact answer."""


class QuantityConstraintSystem:
    """A small named linear/integer constraint set with exact queries."""

    def __init__(self, *, timeout_ms: int = 5_000) -> None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            raise ValueError("timeout_ms must be a positive integer")
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        self._timeout_ms = timeout_ms
        self._variables: dict[str, QuantityVariable] = {}
        self._constraints: list[LinearConstraint] = []
        self._constraint_ids: set[str] = set()

    @property
    def variables(self) -> tuple[QuantityVariable, ...]:
        return tuple(self._variables.values())

    @property
    def constraints(self) -> tuple[LinearConstraint, ...]:
        return tuple(self._constraints)

    def add_variable(self, variable: QuantityVariable) -> None:
        if variable.variable_id in self._variables:
            raise ValueError(f"duplicate quantity variable: {variable.variable_id}")
        domain_constraint_id = f"domain:{variable.variable_id}:nonnegative"
        if domain_constraint_id in self._constraint_ids:
            raise ValueError(
                f"duplicate quantity constraint: {domain_constraint_id}"
            )
        self._variables[variable.variable_id] = variable
        self.add_constraint(
            domain_constraint_id,
            {variable.variable_id: 1},
            ConstraintRelation.AT_LEAST,
            0,
        )

    def add_constraint(
        self,
        constraint_id: str,
        coefficients: Mapping[str, Number],
        relation: ConstraintRelation,
        bound: Number,
    ) -> None:
        stable_id = _nonblank(constraint_id, "constraint_id")
        if stable_id in self._constraint_ids:
            raise ValueError(f"duplicate quantity constraint: {stable_id}")
        if not isinstance(relation, ConstraintRelation):
            raise ValueError("relation must be a ConstraintRelation")

        normalized = []
        units = set()
        for variable_id, raw_coefficient in coefficients.items():
            variable = self._variables.get(variable_id)
            if variable is None:
                raise ValueError(f"unknown quantity variable: {variable_id}")
            coefficient = _fraction(
                raw_coefficient,
                f"{stable_id}.coefficient[{variable_id}]",
            )
            if coefficient == 0:
                continue
            normalized.append((variable_id, coefficient))
            units.add(variable.unit)
        if not normalized:
            raise ValueError("a quantity constraint needs a nonzero term")
        if len(units) != 1:
            raise ValueError("a quantity constraint cannot mix units")

        constraint = LinearConstraint(
            stable_id,
            tuple(sorted(normalized)),
            relation,
            _fraction(bound, f"{stable_id}.bound"),
        )
        self._constraints.append(constraint)
        self._constraint_ids.add(stable_id)

    def is_feasible(self) -> bool:
        return self._is_satisfiable(
            tuple(constraint.constraint_id for constraint in self._constraints),
            deadline=self._deadline(),
        )

    def conflict(self) -> tuple[str, ...]:
        """Return a deletion-minimal incompatible set of named facts."""

        return self._conflict(deadline=self._deadline())

    def _conflict(
        self,
        included_ids: tuple[str, ...] | None = None,
        *,
        deadline: float,
    ) -> tuple[str, ...]:
        solver, tracked = self._solver(
            included_ids=included_ids,
            track=True,
            deadline=deadline,
        )
        status = solver.check()
        if status == z3.unknown:
            raise QuantityQueryIndeterminate(
                f"quantity feasibility query was indeterminate: "
                f"{solver.reason_unknown()}"
            )
        if status != z3.unsat:
            return ()
        core_names = {item.decl().name() for item in solver.unsat_core()}
        candidates = [
            constraint.constraint_id
            for constraint in self._constraints
            if (
                included_ids is None
                or constraint.constraint_id in included_ids
            )
            if tracked[constraint.constraint_id] in core_names
        ]
        index = 0
        while index < len(candidates):
            reduced = candidates[:index] + candidates[index + 1 :]
            if not self._is_satisfiable(tuple(reduced), deadline=deadline):
                candidates = reduced
            else:
                index += 1
        return tuple(candidates)

    def bounds(self, variable_id: str) -> QuantityBounds:
        variable = self._require_variable(variable_id)
        bounds, _, _ = self._expression_bounds(
            {variable_id: 1},
            deadline=self._deadline(),
        )
        return QuantityBounds(
            bounds[0], bounds[1], variable.unit, variable.domain
        )

    def expression_bounds(
        self,
        coefficients: Mapping[str, Number],
    ) -> QuantityBounds:
        normalized, unit, domain = self._normalize_expression(coefficients)
        bounds, _, _ = self._expression_bounds(
            dict(normalized),
            deadline=self._deadline(),
        )
        return QuantityBounds(bounds[0], bounds[1], unit, domain)

    def explain_bounds(self, variable_id: str) -> BoundExplanation:
        return self.explain_expression_bounds({variable_id: Fraction(1)})

    def explain_expression_bounds(
        self,
        coefficients: Mapping[str, Number],
    ) -> BoundExplanation:
        """Explain one pair of sharp bounds with one minimal fact set each."""

        normalized, unit, domain = self._normalize_expression(coefficients)
        expression = dict(normalized)
        deadline = self._deadline()
        bounds, minimum_witness, maximum_witness = self._expression_bounds(
            expression,
            deadline=deadline,
        )
        fact_ids, _ = self._relevant_subsystem(expression)
        minimum_facts = self._minimal_facts_for_bound(
            expression,
            maximize=False,
            target=bounds[0],
            candidates=fact_ids,
            deadline=deadline,
        )
        maximum_facts = self._minimal_facts_for_bound(
            expression,
            maximize=True,
            target=bounds[1],
            candidates=fact_ids,
            deadline=deadline,
        )
        return BoundExplanation(
            QuantityBounds(bounds[0], bounds[1], unit, domain),
            minimum_facts,
            maximum_facts,
            minimum_witness,
            maximum_witness,
        )

    def _require_variable(self, variable_id: str) -> QuantityVariable:
        try:
            return self._variables[variable_id]
        except KeyError as error:
            raise ValueError(
                f"unknown quantity variable: {variable_id}"
            ) from error

    def _normalize_expression(
        self,
        coefficients: Mapping[str, Number],
    ) -> tuple[tuple[tuple[str, Fraction], ...], str, QuantityDomain]:
        normalized = []
        units = set()
        domains = set()
        for variable_id, raw_coefficient in coefficients.items():
            variable = self._require_variable(variable_id)
            coefficient = _fraction(
                raw_coefficient,
                f"expression.coefficient[{variable_id}]",
            )
            if coefficient == 0:
                continue
            normalized.append((variable_id, coefficient))
            units.add(variable.unit)
            domains.add(variable.domain)
        if not normalized:
            raise ValueError("a quantity expression needs a nonzero term")
        if len(units) != 1:
            raise ValueError("a quantity expression cannot mix units")
        domain = (
            QuantityDomain.DISCRETE
            if domains == {QuantityDomain.DISCRETE}
            and all(value.denominator == 1 for _, value in normalized)
            else QuantityDomain.CONTINUOUS
        )
        return tuple(sorted(normalized)), units.pop(), domain

    def _expression_bounds(
        self,
        coefficients: Mapping[str, Number],
        *,
        deadline: float,
    ) -> tuple[
        tuple[Fraction | None, Fraction | None],
        tuple[tuple[str, Fraction], ...],
        tuple[tuple[str, Fraction], ...],
    ]:
        fact_ids, witness_variable_ids = self._relevant_subsystem(coefficients)
        if not self._is_satisfiable(fact_ids, deadline=deadline):
            raise InfeasibleQuantityFacts(
                self._conflict(fact_ids, deadline=deadline)
            )
        minimum, minimum_witness = self._optimize(
            coefficients,
            maximize=False,
            included_ids=fact_ids,
            witness_variable_ids=witness_variable_ids,
            deadline=deadline,
        )
        maximum, maximum_witness = self._optimize(
            coefficients,
            maximize=True,
            included_ids=fact_ids,
            witness_variable_ids=witness_variable_ids,
            deadline=deadline,
        )
        return (minimum, maximum), minimum_witness, maximum_witness

    def _relevant_subsystem(
        self,
        coefficients: Mapping[str, Number],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Find facts transitively connected to the queried quantities."""

        relevant_variables = set(coefficients)
        relevant_constraints: set[str] = set()
        changed = True
        while changed:
            changed = False
            for constraint in self._constraints:
                if constraint.constraint_id in relevant_constraints:
                    continue
                term_variables = {
                    variable_id
                    for variable_id, _ in constraint.coefficients
                }
                if not term_variables.intersection(relevant_variables):
                    continue
                relevant_constraints.add(constraint.constraint_id)
                before = len(relevant_variables)
                relevant_variables.update(term_variables)
                changed = changed or len(relevant_variables) != before
        ordered_constraints = tuple(
            constraint.constraint_id
            for constraint in self._constraints
            if constraint.constraint_id in relevant_constraints
        )
        ordered_variables = tuple(
            variable_id
            for variable_id in self._variables
            if variable_id in relevant_variables
        )
        return ordered_constraints, ordered_variables

    def _minimal_facts_for_bound(
        self,
        coefficients: Mapping[str, Number],
        *,
        maximize: bool,
        target: Fraction | None,
        candidates: tuple[str, ...],
        deadline: float,
    ) -> tuple[str, ...]:
        if target is None:
            return ()
        retained = list(candidates)
        index = 0
        while index < len(retained):
            reduced = retained[:index] + retained[index + 1 :]
            if self._facts_enforce_bound(
                coefficients,
                maximize=maximize,
                target=target,
                included_ids=tuple(reduced),
                deadline=deadline,
            ):
                retained = reduced
            else:
                index += 1
        return tuple(retained)

    def _facts_enforce_bound(
        self,
        coefficients: Mapping[str, Number],
        *,
        maximize: bool,
        target: Fraction,
        included_ids: tuple[str, ...],
        deadline: float,
    ) -> bool:
        """Whether the selected facts make any better value impossible."""

        normalized, _, _ = self._normalize_expression(coefficients)
        variables = self._z3_variables()
        solver, _ = self._solver(
            included_ids=included_ids,
            deadline=deadline,
        )
        expression = z3.Sum([
            self._z3_number(coefficient) * variables[variable_id]
            for variable_id, coefficient in normalized
        ])
        target_value = self._z3_number(target)
        solver.add(
            expression > target_value
            if maximize
            else expression < target_value
        )
        status = solver.check()
        if status == z3.unknown:
            raise QuantityQueryIndeterminate(
                f"quantity explanation query was indeterminate: "
                f"{solver.reason_unknown()}"
            )
        return status == z3.unsat

    def _is_satisfiable(
        self,
        included_ids: tuple[str, ...],
        *,
        deadline: float,
    ) -> bool:
        solver, _ = self._solver(
            included_ids=included_ids,
            deadline=deadline,
        )
        status = solver.check()
        if status == z3.unknown:
            raise QuantityQueryIndeterminate(
                f"quantity feasibility query was indeterminate: "
                f"{solver.reason_unknown()}"
            )
        return status == z3.sat

    def _solver(
        self,
        included_ids: tuple[str, ...] | None = None,
        *,
        track: bool = False,
        deadline: float,
    ) -> tuple[z3.Solver, dict[str, str]]:
        variables = self._z3_variables()
        solver = z3.Solver()
        solver.set(timeout=self._remaining_timeout_ms(deadline))
        included = set(included_ids) if included_ids is not None else None
        tracked: dict[str, str] = {}
        for index, constraint in enumerate(self._constraints):
            if included is not None and constraint.constraint_id not in included:
                continue
            expression = self._z3_constraint(constraint, variables)
            if track:
                tracker_name = f"quantity_fact_{index}"
                solver.assert_and_track(expression, z3.Bool(tracker_name))
                tracked[constraint.constraint_id] = tracker_name
            else:
                solver.add(expression)
        return solver, tracked

    def _optimize(
        self,
        coefficients: Mapping[str, Number],
        *,
        maximize: bool,
        included_ids: tuple[str, ...] | None = None,
        witness_variable_ids: tuple[str, ...] | None = None,
        deadline: float,
    ) -> tuple[Fraction | None, tuple[tuple[str, Fraction], ...]]:
        normalized, _, _ = self._normalize_expression(coefficients)
        variables = self._z3_variables()
        optimizer = z3.Optimize()
        optimizer.set(timeout=self._remaining_timeout_ms(deadline))
        included = set(included_ids) if included_ids is not None else None
        for constraint in self._constraints:
            if included is not None and constraint.constraint_id not in included:
                continue
            optimizer.add(self._z3_constraint(constraint, variables))
        expression = z3.Sum([
            self._z3_number(coefficient) * variables[variable_id]
            for variable_id, coefficient in normalized
        ])
        objective = (
            optimizer.maximize(expression)
            if maximize
            else optimizer.minimize(expression)
        )
        status = optimizer.check()
        if status == z3.unsat:
            raise InfeasibleQuantityFacts(
                self._conflict(included_ids, deadline=deadline)
            )
        if status != z3.sat:
            raise QuantityQueryIndeterminate(
                f"quantity optimization query was indeterminate: "
                f"{optimizer.reason_unknown()}"
            )
        raw_value = objective.value()
        value = (
            None
            if "oo" in str(raw_value)
            else self._fraction_from_z3(raw_value)
        )
        witness = ()
        if value is not None:
            model = optimizer.model()
            selected_variables = (
                set(witness_variable_ids)
                if witness_variable_ids is not None
                else set(variables)
            )
            witness = tuple(sorted(
                (
                    variable_id,
                    self._fraction_from_z3(
                        model.evaluate(variable, model_completion=True)
                    ),
                )
                for variable_id, variable in variables.items()
                if variable_id in selected_variables
            ))
        return value, witness

    def _deadline(self) -> float:
        return monotonic() + (self._timeout_ms / 1_000)

    @staticmethod
    def _remaining_timeout_ms(deadline: float) -> int:
        remaining = int((deadline - monotonic()) * 1_000)
        if remaining <= 0:
            raise QuantityQueryIndeterminate(
                "quantity query exceeded its end-to-end time budget"
            )
        return remaining

    def _z3_variables(self) -> dict[str, z3.ArithRef]:
        return {
            variable.variable_id: (
                z3.Int(variable.variable_id)
                if variable.domain == QuantityDomain.DISCRETE
                else z3.Real(variable.variable_id)
            )
            for variable in self._variables.values()
        }

    @classmethod
    def _z3_constraint(
        cls,
        constraint: LinearConstraint,
        variables: Mapping[str, z3.ArithRef],
    ) -> z3.BoolRef:
        expression = z3.Sum([
            cls._z3_number(coefficient) * variables[variable_id]
            for variable_id, coefficient in constraint.coefficients
        ])
        bound = cls._z3_number(constraint.bound)
        if constraint.relation == ConstraintRelation.EQUAL:
            return expression == bound
        if constraint.relation == ConstraintRelation.AT_LEAST:
            return expression >= bound
        return expression <= bound

    @staticmethod
    def _z3_number(value: Fraction) -> z3.RatNumRef:
        return z3.RealVal(f"{value.numerator}/{value.denominator}")

    @staticmethod
    def _fraction_from_z3(value: z3.ArithRef) -> Fraction:
        if z3.is_int_value(value):
            return Fraction(value.as_long())
        if z3.is_rational_value(value):
            return Fraction(
                value.numerator_as_long(), value.denominator_as_long()
            )
        raise RuntimeError(f"quantity solver returned a non-rational value: {value}")


@dataclass(frozen=True)
class HoldingState:
    """One immutable time-slice variable for a physical holding."""

    holding: HoldingKey
    domain: QuantityDomain
    revision: int
    variable_id: str


@dataclass(frozen=True, init=False)
class QuantityObservation:
    """A quantity claim; the preferred value is evidence, not a constraint."""

    observation_id: str
    lower: Fraction | None
    preferred: Fraction | None
    upper: Fraction | None
    basis: ObservationBasis

    def __init__(
        self,
        observation_id: str,
        *,
        lower: Number | None = None,
        preferred: Number | None = None,
        upper: Number | None = None,
        basis: ObservationBasis,
    ):
        stable_id = _nonblank(observation_id, "observation_id")
        values = {
            "lower": None if lower is None else _fraction(lower, "lower"),
            "preferred": (
                None if preferred is None else _fraction(preferred, "preferred")
            ),
            "upper": None if upper is None else _fraction(upper, "upper"),
        }
        if all(value is None for value in values.values()):
            raise ValueError("an observation needs a bound or preferred value")
        if any(value is not None and value < 0 for value in values.values()):
            raise ValueError("observation quantities must be nonnegative")
        if values["lower"] is not None and values["upper"] is not None:
            if values["lower"] > values["upper"]:
                raise ValueError("observation lower bound exceeds upper bound")
        if values["preferred"] is not None:
            if (
                values["lower"] is not None
                and values["preferred"] < values["lower"]
            ):
                raise ValueError("preferred quantity is below the lower bound")
            if (
                values["upper"] is not None
                and values["preferred"] > values["upper"]
            ):
                raise ValueError("preferred quantity is above the upper bound")
        if not isinstance(basis, ObservationBasis):
            raise ValueError("basis must be an ObservationBasis")
        object.__setattr__(self, "observation_id", stable_id)
        object.__setattr__(self, "lower", values["lower"])
        object.__setattr__(self, "preferred", values["preferred"])
        object.__setattr__(self, "upper", values["upper"])
        object.__setattr__(self, "basis", basis)

    @classmethod
    def exact(
        cls,
        observation_id: str,
        amount: Number,
        *,
        basis: ObservationBasis,
    ) -> QuantityObservation:
        value = _fraction(amount, "amount")
        return cls(
            observation_id,
            lower=value,
            preferred=value,
            upper=value,
            basis=basis,
        )

    @classmethod
    def estimated(
        cls,
        observation_id: str,
        preferred: Number,
        *,
        lower: Number = 0,
        upper: Number | None = None,
    ) -> QuantityObservation:
        """Create a rough estimate, defaulting its upper bound to twice it."""

        estimate = _positive_fraction(preferred, "preferred")
        return cls(
            observation_id,
            lower=lower,
            preferred=estimate,
            upper=estimate * 2 if upper is None else upper,
            basis=ObservationBasis.ESTIMATED,
        )


class QuantityHistory:
    """Append-only evidence about possible physical quantity histories.

    This is deliberately not the authoritative ledger projection. Observations
    narrow physical possibilities here; accepting a reconciliation into book
    inventory remains a separate command and policy decision.
    """

    def __init__(self, *, query_timeout_ms: int = 5_000) -> None:
        self._system = QuantityConstraintSystem(timeout_ms=query_timeout_ms)
        self._current: dict[HoldingKey, HoldingState] = {}
        self._events: set[str] = set()
        self._observations: list[tuple[HoldingState, QuantityObservation]] = []
        self._withdrawals: dict[tuple[str, HoldingKey], str] = {}
        self._states: dict[str, HoldingState] = {}
        self._next_variable = 0

    @property
    def observations(
        self,
    ) -> tuple[tuple[HoldingState, QuantityObservation], ...]:
        return tuple(self._observations)

    @property
    def constraints(self) -> tuple[LinearConstraint, ...]:
        return self._system.constraints

    def open_holding(
        self,
        holding: HoldingKey,
        domain: QuantityDomain,
        observation: QuantityObservation,
    ) -> HoldingState:
        if holding in self._current:
            raise ValueError("holding already has an opening state")
        if not isinstance(domain, QuantityDomain):
            raise ValueError("domain must be a QuantityDomain")
        self._validate_new_event(observation.observation_id)
        self._validate_observation(domain, observation)
        state = self._new_state(holding, domain, revision=0)
        self._add_observation_constraints(state, observation)
        self._events.add(observation.observation_id)
        self._observations.append((state, observation))
        self._current[holding] = state
        return state

    def observe_current(
        self,
        holding: HoldingKey,
        observation: QuantityObservation,
    ) -> HoldingState:
        state = self.current_state(holding)
        self._validate_new_event(observation.observation_id)
        self._validate_observation(state.domain, observation)
        self._add_observation_constraints(state, observation)
        self._events.add(observation.observation_id)
        self._observations.append((state, observation))
        return state

    def record_exact_withdrawal(
        self,
        operation_id: str,
        holding: HoldingKey,
        amount: Number,
    ) -> HoldingState:
        """Retain an already-observed withdrawal, even if facts then conflict."""

        stable_id = self._validate_new_event(operation_id)
        before = self.current_state(holding)
        quantity = self._validate_amount(before.domain, amount, "amount")
        after = self._new_state(
            holding,
            before.domain,
            revision=before.revision + 1,
        )
        self._system.add_constraint(
            f"{stable_id}:balance",
            {before.variable_id: 1, after.variable_id: -1},
            ConstraintRelation.EQUAL,
            quantity,
        )
        self._events.add(stable_id)
        self._current[holding] = after
        self._withdrawals[(stable_id, holding)] = ""
        return after

    def record_withdrawal_from_sources(
        self,
        operation_id: str,
        holdings: Sequence[HoldingKey],
        total: Number,
    ) -> tuple[HoldingState, ...]:
        """Retain a withdrawal whose allocation across sources is unknown."""

        stable_id = self._validate_new_event(operation_id)
        sources = tuple(holdings)
        if len(sources) < 2:
            raise ValueError("an uncertain source withdrawal needs two holdings")
        if len(set(sources)) != len(sources):
            raise ValueError("withdrawal sources must be unique")
        before_states = tuple(self.current_state(source) for source in sources)
        first = before_states[0]
        self._require_compatible_states(
            before_states,
            "withdrawal sources",
        )
        quantity = self._validate_amount(first.domain, total, "total")

        after_states = []
        draw_variables = []
        for index, (source, before) in enumerate(zip(sources, before_states)):
            draw_id = self._next_variable_id()
            self._system.add_variable(
                QuantityVariable(draw_id, source.unit, before.domain)
            )
            after = self._new_state(
                source,
                before.domain,
                revision=before.revision + 1,
            )
            self._system.add_constraint(
                f"{stable_id}:source:{index}",
                {
                    before.variable_id: 1,
                    after.variable_id: -1,
                    draw_id: -1,
                },
                ConstraintRelation.EQUAL,
                0,
            )
            draw_variables.append(draw_id)
            after_states.append(after)
        self._system.add_constraint(
            f"{stable_id}:total",
            {draw_id: 1 for draw_id in draw_variables},
            ConstraintRelation.EQUAL,
            quantity,
        )

        self._events.add(stable_id)
        for source, after, draw_id in zip(
            sources, after_states, draw_variables
        ):
            self._current[source] = after
            self._withdrawals[(stable_id, source)] = draw_id
        return tuple(after_states)

    def current_state(self, holding: HoldingKey) -> HoldingState:
        try:
            return self._current[holding]
        except KeyError as error:
            raise ValueError("holding has no quantity state") from error

    def bounds(self, state: HoldingState) -> QuantityBounds:
        self._require_state(state)
        return self._system.bounds(state.variable_id)

    def current_physical_bounds(self, holding: HoldingKey) -> QuantityBounds:
        """Return feasible physical bounds, not accepted book inventory."""

        return self.bounds(self.current_state(holding))

    def explain(self, state: HoldingState) -> BoundExplanation:
        self._require_state(state)
        return self._system.explain_bounds(state.variable_id)

    def current_total_bounds(
        self,
        holdings: Sequence[HoldingKey],
    ) -> QuantityBounds:
        """Bound a total over distinct holdings at the current snapshot."""

        selected = tuple(holdings)
        if not selected:
            raise ValueError("a total needs at least one holding state")
        if len(set(selected)) != len(selected):
            raise ValueError("a current total needs distinct holdings")
        coefficients = self._current_total_expression(selected)
        return self._system.expression_bounds(coefficients)

    def explain_current_total(
        self,
        holdings: Sequence[HoldingKey],
    ) -> BoundExplanation:
        """Explain a total over distinct holdings at the current snapshot."""

        coefficients = self._current_total_expression(tuple(holdings))
        return self._system.explain_expression_bounds(
            coefficients
        )

    def withdrawal_bounds(
        self,
        operation_id: str,
        holding: HoldingKey,
    ) -> QuantityBounds:
        variable_id = self._withdrawal_variable(operation_id, holding)
        return self._system.bounds(variable_id)

    def explain_withdrawal(
        self,
        operation_id: str,
        holding: HoldingKey,
    ) -> BoundExplanation:
        """Explain one source allocation within an uncertain withdrawal."""

        variable_id = self._withdrawal_variable(operation_id, holding)
        return self._system.explain_bounds(variable_id)

    def _withdrawal_variable(
        self,
        operation_id: str,
        holding: HoldingKey,
    ) -> str:
        key = (operation_id, holding)
        if key not in self._withdrawals:
            raise ValueError("operation has no withdrawal from that holding")
        variable_id = self._withdrawals[key]
        if not variable_id:
            raise ValueError("single-source withdrawal is already exact")
        return variable_id

    def is_feasible(self) -> bool:
        return self._system.is_feasible()

    def conflict(self) -> tuple[str, ...]:
        return self._system.conflict()

    def _new_state(
        self,
        holding: HoldingKey,
        domain: QuantityDomain,
        revision: int,
    ) -> HoldingState:
        variable_id = self._next_variable_id()
        self._system.add_variable(
            QuantityVariable(variable_id, holding.unit, domain)
        )
        state = HoldingState(holding, domain, revision, variable_id)
        self._states[variable_id] = state
        return state

    def _next_variable_id(self) -> str:
        variable_id = f"quantity_{self._next_variable}"
        self._next_variable += 1
        return variable_id

    def _current_total_expression(
        self,
        holdings: tuple[HoldingKey, ...],
    ) -> dict[str, int]:
        if not holdings:
            raise ValueError("a total needs at least one holding state")
        if len(set(holdings)) != len(holdings):
            raise ValueError("a current total needs distinct holdings")
        states = tuple(self.current_state(holding) for holding in holdings)
        self._require_compatible_states(states, "a current total")
        return {state.variable_id: 1 for state in states}

    @staticmethod
    def _require_compatible_states(
        states: Sequence[HoldingState],
        subject: str,
    ) -> None:
        first = states[0]
        signature = (
            first.holding.batch_id,
            first.holding.unit,
            first.holding.packaging_configuration_id,
            first.domain,
        )
        if any(
            (
                state.holding.batch_id,
                state.holding.unit,
                state.holding.packaging_configuration_id,
                state.domain,
            )
            != signature
            for state in states[1:]
        ):
            raise ValueError(
                f"{subject} need one compatible batch, unit, package "
                "configuration, and numeric domain"
            )

    def _add_observation_constraints(
        self,
        state: HoldingState,
        observation: QuantityObservation,
    ) -> None:
        if (
            observation.lower is not None
            and observation.lower == observation.upper
        ):
            self._system.add_constraint(
                f"{observation.observation_id}:exact",
                {state.variable_id: 1},
                ConstraintRelation.EQUAL,
                observation.lower,
            )
            return
        if observation.lower is not None:
            self._system.add_constraint(
                f"{observation.observation_id}:lower",
                {state.variable_id: 1},
                ConstraintRelation.AT_LEAST,
                observation.lower,
            )
        if observation.upper is not None:
            self._system.add_constraint(
                f"{observation.observation_id}:upper",
                {state.variable_id: 1},
                ConstraintRelation.AT_MOST,
                observation.upper,
            )

    @staticmethod
    def _validate_observation(
        domain: QuantityDomain,
        observation: QuantityObservation,
    ) -> None:
        if domain == QuantityDomain.DISCRETE:
            for value in (
                observation.lower,
                observation.preferred,
                observation.upper,
            ):
                if value is not None and value.denominator != 1:
                    raise ValueError("discrete observations must use whole amounts")

    @staticmethod
    def _validate_amount(
        domain: QuantityDomain,
        amount: Number,
        field: str,
    ) -> Fraction:
        value = _positive_fraction(amount, field)
        if domain == QuantityDomain.DISCRETE and value.denominator != 1:
            raise ValueError(f"discrete {field} must be a whole amount")
        return value

    def _validate_new_event(self, event_id: str) -> str:
        stable_id = _nonblank(event_id, "event_id")
        if stable_id in self._events:
            raise ValueError(f"duplicate quantity event: {stable_id}")
        return stable_id

    def _require_state(self, state: HoldingState) -> None:
        if not isinstance(state, HoldingState):
            raise ValueError("state must be a HoldingState")
        if self._states.get(state.variable_id) is not state:
            raise ValueError("holding state belongs to another history")
