"""Persistence-free process and observation compiler for quantity reasoning.

This is the executable design seam that follows the rejected RC7
``quantity-withdrawal`` product boundary.  Durable processes say what
participated and what they produced.  The compiler creates temporary holding
states, flow allocations, and linear constraints; source remainders are query
results rather than process outputs or stored facts.

The module deliberately has no Flask, MongoDB, codec, or authorization surface.
It exists so the semantic model can be exercised before persistence makes it
expensive to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Sequence

from inventorius.ledger import HoldingKey
from inventorius.quantity_constraints import (
    BoundExplanation,
    ConstraintRelation,
    HoldingState,
    LinearConstraint,
    Number,
    QuantityBounds,
    QuantityConstraintSystem,
    QuantityDomain,
    QuantityObservation,
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
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError(f"{field} must be an exact number") from error
    else:
        raise ValueError(f"{field} must be an int, decimal string, or Fraction")
    return result


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value


@dataclass(frozen=True, init=False)
class ExactAmount:
    """One positive exact amount participating in a process flow."""

    amount: Fraction

    def __init__(self, amount: Number):
        value = _fraction(amount, "amount")
        if value <= 0:
            raise ValueError("amount must be positive")
        object.__setattr__(self, "amount", value)


@dataclass(frozen=True)
class AllRemaining:
    """Consume the complete quantity then feasible in one holding."""


ALL_REMAINING = AllRemaining()


@dataclass(frozen=True)
class FromInput:
    """Produce exactly the amount compiled for one process input."""

    input_id: str

    def __post_init__(self) -> None:
        _nonblank(self.input_id, "input_id")


InputAmount = ExactAmount | AllRemaining
OutputAmount = ExactAmount | FromInput


@dataclass(frozen=True)
class ProcessInput:
    """A quantity consumed from one holding or an unresolved candidate set."""

    input_id: str
    candidates: tuple[HoldingKey, ...]
    amount: InputAmount
    role: str = "input"
    selector: str | None = None
    contributes_to: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonblank(self.input_id, "input_id")
        _nonblank(self.role, "role")
        if not self.candidates:
            raise ValueError("a process input needs at least one candidate holding")
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("process input candidates must be distinct")
        if not isinstance(self.amount, (ExactAmount, AllRemaining)):
            raise ValueError("process input amount has an unsupported type")
        if isinstance(self.amount, AllRemaining) and len(self.candidates) != 1:
            raise ValueError("all remaining requires one exact holding")
        if len(self.candidates) > 1:
            _nonblank(self.selector, "selector")
        elif self.selector is not None:
            _nonblank(self.selector, "selector")
        if len(set(self.contributes_to)) != len(self.contributes_to):
            raise ValueError("contributes_to output identifiers must be distinct")
        for output_id in self.contributes_to:
            _nonblank(output_id, "contributes_to output identifier")


@dataclass(frozen=True)
class ProcessOutput:
    """A quantity produced into one concrete holding."""

    output_id: str
    holding: HoldingKey
    domain: QuantityDomain
    amount: OutputAmount
    role: str = "output"

    def __post_init__(self) -> None:
        _nonblank(self.output_id, "output_id")
        _nonblank(self.role, "role")
        if not isinstance(self.holding, HoldingKey):
            raise ValueError("process output holding must be a HoldingKey")
        if not isinstance(self.domain, QuantityDomain):
            raise ValueError("process output domain must be a QuantityDomain")
        if not isinstance(self.amount, (ExactAmount, FromInput)):
            raise ValueError("process output amount has an unsupported type")


@dataclass(frozen=True)
class ProcessSink:
    """An explicit external destination for one compiled input quantity."""

    sink_id: str
    kind: str
    unit: str
    domain: QuantityDomain
    amount: FromInput
    note: str = ""

    def __post_init__(self) -> None:
        _nonblank(self.sink_id, "sink_id")
        _nonblank(self.kind, "kind")
        _nonblank(self.unit, "unit")
        if not isinstance(self.domain, QuantityDomain):
            raise ValueError("process sink domain must be a QuantityDomain")
        if not isinstance(self.amount, FromInput):
            raise ValueError("process sink must reference one process input")


@dataclass(frozen=True)
class ProcessEvent:
    """One physical or identity-changing process known to Inventorius."""

    process_id: str
    kind: str
    occurred_at: datetime
    recorded_at: datetime
    inputs: tuple[ProcessInput, ...] = ()
    outputs: tuple[ProcessOutput, ...] = ()
    sinks: tuple[ProcessSink, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        _nonblank(self.process_id, "process_id")
        _nonblank(self.kind, "kind")
        occurred = _aware(self.occurred_at, "occurred_at")
        recorded = _aware(self.recorded_at, "recorded_at")
        if recorded < occurred:
            raise ValueError("recorded_at cannot precede occurred_at")
        if not self.inputs:
            raise ValueError(
                "output-only processes need explicit external-source semantics"
            )
        input_ids = [item.input_id for item in self.inputs]
        output_ids = [item.output_id for item in self.outputs]
        sink_ids = [item.sink_id for item in self.sinks]
        if len(set(input_ids)) != len(input_ids):
            raise ValueError("process input identifiers must be distinct")
        if len(set(output_ids)) != len(output_ids):
            raise ValueError("process output identifiers must be distinct")
        if len(set(sink_ids)) != len(sink_ids):
            raise ValueError("process sink identifiers must be distinct")
        known_inputs = set(input_ids)
        for output in self.outputs:
            if (
                isinstance(output.amount, FromInput)
                and output.amount.input_id not in known_inputs
            ):
                raise ValueError("process output references an unknown input")
            if isinstance(output.amount, FromInput):
                source = next(
                    item
                    for item in self.inputs
                    if item.input_id == output.amount.input_id
                )
                if len(source.candidates) > 1:
                    raise ValueError(
                        "an ambiguous input cannot become one concrete output "
                        "Batch without allocation semantics"
                    )
        for sink in self.sinks:
            if sink.amount.input_id not in known_inputs:
                raise ValueError("process sink references an unknown input")
        known_outputs = set(output_ids)
        for process_input in self.inputs:
            unknown = set(process_input.contributes_to) - known_outputs
            if unknown:
                raise ValueError("process input contributes to an unknown output")
            accounted = any(
                isinstance(output.amount, FromInput)
                and output.amount.input_id == process_input.input_id
                for output in self.outputs
            ) or any(
                sink.amount.input_id == process_input.input_id
                for sink in self.sinks
            ) or bool(process_input.contributes_to)
            if not accounted:
                raise ValueError(
                    "every process input needs an output, sink, or structural "
                    "contribution"
                )
        touched_inputs = [
            holding for item in self.inputs for holding in item.candidates
        ]
        touched_outputs = [item.holding for item in self.outputs]
        if len(set(touched_inputs)) != len(touched_inputs):
            raise ValueError("one process cannot consume a holding twice")
        if len(set(touched_outputs)) != len(touched_outputs):
            raise ValueError("one process cannot produce into a holding twice")
        if set(touched_inputs) & set(touched_outputs):
            raise ValueError(
                "same-holding input/output semantics are not defined yet"
            )


@dataclass(frozen=True)
class ObservationEvent:
    """A non-consuming claim about one holding at one occurrence time."""

    holding: HoldingKey
    domain: QuantityDomain
    observation: QuantityObservation
    occurred_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.holding, HoldingKey):
            raise ValueError("observation holding must be a HoldingKey")
        if not isinstance(self.domain, QuantityDomain):
            raise ValueError("observation domain must be a QuantityDomain")
        if not isinstance(self.observation, QuantityObservation):
            raise ValueError("observation must be a QuantityObservation")
        occurred = _aware(self.occurred_at, "occurred_at")
        recorded = _aware(self.recorded_at, "recorded_at")
        if recorded < occurred:
            raise ValueError("recorded_at cannot precede occurred_at")

    @property
    def event_id(self) -> str:
        return self.observation.observation_id


QuantityEvent = ProcessEvent | ObservationEvent


class ProcessQuantityTimeline:
    """Append recorded events and recompile physical history when queried."""

    def __init__(self, *, query_timeout_ms: int = 5_000) -> None:
        self._query_timeout_ms = query_timeout_ms
        self._events: list[QuantityEvent] = []
        self._event_ids: set[str] = set()

    @property
    def events(self) -> tuple[QuantityEvent, ...]:
        return tuple(self._events)

    def record(self, event: QuantityEvent) -> None:
        if not isinstance(event, (ProcessEvent, ObservationEvent)):
            raise ValueError("event must be a process or observation")
        event_id = _event_id(event)
        if event_id in self._event_ids:
            raise ValueError(f"duplicate quantity event: {event_id}")
        self._events.append(event)
        self._event_ids.add(event_id)

    def compile(
        self,
        *,
        known_at: datetime | None = None,
    ) -> CompiledProcessQuantities:
        if known_at is not None:
            _aware(known_at, "known_at")
        events = [
            event
            for event in self._events
            if known_at is None or event.recorded_at <= known_at
        ]
        events.sort(
            key=lambda event: (
                event.occurred_at,
                event.recorded_at,
                _event_id(event),
            )
        )
        return _ProcessCompiler(self._query_timeout_ms).compile(events)


class CompiledProcessQuantities:
    """One disposable solver projection of the recorded process timeline."""

    def __init__(
        self,
        system: QuantityConstraintSystem,
        current: dict[HoldingKey, HoldingState],
        input_variables: dict[tuple[str, str], str],
        allocation_variables: dict[tuple[str, str, HoldingKey], str],
        labels: dict[str, str],
        event_order: tuple[str, ...],
    ) -> None:
        self._system = system
        self._current = current
        self._input_variables = input_variables
        self._allocation_variables = allocation_variables
        self._labels = labels
        self._event_order = event_order

    @property
    def constraints(self) -> tuple[LinearConstraint, ...]:
        return self._system.constraints

    @property
    def event_order(self) -> tuple[str, ...]:
        return self._event_order

    @property
    def holdings(self) -> tuple[HoldingKey, ...]:
        return tuple(self._current)

    def is_feasible(self) -> bool:
        return self._system.is_feasible()

    def conflict(self) -> tuple[str, ...]:
        return self._system.conflict()

    def current_bounds(self, holding: HoldingKey) -> QuantityBounds:
        try:
            state = self._current[holding]
        except KeyError as error:
            raise ValueError("holding has no compiled quantity state") from error
        return self._system.bounds(state.variable_id)

    def explain_current(self, holding: HoldingKey) -> BoundExplanation:
        try:
            state = self._current[holding]
        except KeyError as error:
            raise ValueError("holding has no compiled quantity state") from error
        return self._system.explain_bounds(state.variable_id)

    def current_total_bounds(
        self,
        holdings: Sequence[HoldingKey],
    ) -> QuantityBounds:
        selected = tuple(holdings)
        if not selected:
            raise ValueError("a current total needs at least one holding")
        if len(set(selected)) != len(selected):
            raise ValueError("a current total needs distinct holdings")
        states = []
        for holding in selected:
            try:
                states.append(self._current[holding])
            except KeyError as error:
                raise ValueError(
                    "holding has no compiled quantity state"
                ) from error
        _require_compatible(states, "current total", require_batch=False)
        return self._system.expression_bounds(
            {state.variable_id: 1 for state in states}
        )

    def input_bounds(self, process_id: str, input_id: str) -> QuantityBounds:
        try:
            variable_id = self._input_variables[(process_id, input_id)]
        except KeyError as error:
            raise ValueError("process input has no compiled quantity") from error
        return self._system.bounds(variable_id)

    def allocation_bounds(
        self,
        process_id: str,
        input_id: str,
        holding: HoldingKey,
    ) -> QuantityBounds:
        try:
            variable_id = self._allocation_variables[
                (process_id, input_id, holding)
            ]
        except KeyError as error:
            raise ValueError(
                "process input has no allocation for that holding"
            ) from error
        return self._system.bounds(variable_id)

    def rendered_constraints(self) -> tuple[str, ...]:
        """Return readable algebra without exposing generated Z3 expressions."""

        return tuple(
            _render_constraint(constraint, self._labels)
            for constraint in self._system.constraints
            if not constraint.constraint_id.startswith("domain:")
        )


class _ProcessCompiler:
    def __init__(self, timeout_ms: int) -> None:
        self._system = QuantityConstraintSystem(timeout_ms=timeout_ms)
        self._current: dict[HoldingKey, HoldingState] = {}
        self._revisions: dict[HoldingKey, int] = {}
        self._input_variables: dict[tuple[str, str], str] = {}
        self._allocation_variables: dict[
            tuple[str, str, HoldingKey], str
        ] = {}
        self._labels: dict[str, str] = {}

    def compile(
        self,
        events: Sequence[QuantityEvent],
    ) -> CompiledProcessQuantities:
        order = []
        for event in events:
            order.append(_event_id(event))
            if isinstance(event, ObservationEvent):
                self._compile_observation(event)
            else:
                self._compile_process(event)
        return CompiledProcessQuantities(
            self._system,
            dict(self._current),
            dict(self._input_variables),
            dict(self._allocation_variables),
            dict(self._labels),
            tuple(order),
        )

    def _compile_observation(self, event: ObservationEvent) -> None:
        state = self._current.get(event.holding)
        if state is None:
            state = self._new_state(event.holding, event.domain)
            self._current[event.holding] = state
        elif state.domain != event.domain:
            raise ValueError("observation domain does not match holding state")
        _validate_observation(event.domain, event.observation)
        observation = event.observation
        if (
            observation.lower is not None
            and observation.lower == observation.upper
        ):
            self._system.add_constraint(
                f"{event.event_id}:exact",
                {state.variable_id: 1},
                ConstraintRelation.EQUAL,
                observation.lower,
            )
            return
        if observation.lower is not None:
            self._system.add_constraint(
                f"{event.event_id}:lower",
                {state.variable_id: 1},
                ConstraintRelation.AT_LEAST,
                observation.lower,
            )
        if observation.upper is not None:
            self._system.add_constraint(
                f"{event.event_id}:upper",
                {state.variable_id: 1},
                ConstraintRelation.AT_MOST,
                observation.upper,
            )

    def _compile_process(self, event: ProcessEvent) -> None:
        input_variables: dict[str, str] = {}
        for process_input in event.inputs:
            variable_id = self._compile_input(event, process_input)
            input_variables[process_input.input_id] = variable_id
        for output in event.outputs:
            self._compile_output(event, output, input_variables)
        for sink in event.sinks:
            self._compile_sink(event, sink, input_variables)

    def _compile_input(
        self,
        event: ProcessEvent,
        process_input: ProcessInput,
    ) -> str:
        before_states = []
        for holding in process_input.candidates:
            try:
                before_states.append(self._current[holding])
            except KeyError as error:
                raise ValueError(
                    f"process input holding has no earlier state: {holding}"
                ) from error
        _require_compatible(
            before_states,
            "process input candidates",
            require_batch=False,
        )
        domain = before_states[0].domain
        unit = before_states[0].holding.unit
        flow_id = f"flow:{event.process_id}:{process_input.input_id}"
        self._add_variable(
            flow_id,
            unit,
            domain,
            f"flow[{event.process_id}.{process_input.input_id}]",
        )
        self._input_variables[
            (event.process_id, process_input.input_id)
        ] = flow_id

        if isinstance(process_input.amount, ExactAmount):
            _validate_amount(domain, process_input.amount.amount, "input amount")
            self._system.add_constraint(
                f"{event.process_id}:{process_input.input_id}:amount",
                {flow_id: 1},
                ConstraintRelation.EQUAL,
                process_input.amount.amount,
            )

        if len(before_states) == 1:
            before = before_states[0]
            after = self._new_state(before.holding, before.domain)
            self._system.add_constraint(
                f"{event.process_id}:{process_input.input_id}:source",
                {
                    before.variable_id: 1,
                    after.variable_id: -1,
                    flow_id: -1,
                },
                ConstraintRelation.EQUAL,
                0,
            )
            if isinstance(process_input.amount, AllRemaining):
                self._system.add_constraint(
                    f"{event.process_id}:{process_input.input_id}:all",
                    {after.variable_id: 1},
                    ConstraintRelation.EQUAL,
                    0,
                )
            self._current[before.holding] = after
            return flow_id

        allocation_ids = []
        for index, before in enumerate(before_states):
            allocation_id = (
                f"allocation:{event.process_id}:{process_input.input_id}:{index}"
            )
            self._add_variable(
                allocation_id,
                unit,
                domain,
                (
                    f"allocation[{event.process_id}.{process_input.input_id}"
                    f" <- {_holding_label(before.holding)}]"
                ),
            )
            after = self._new_state(before.holding, before.domain)
            self._system.add_constraint(
                f"{event.process_id}:{process_input.input_id}:source:{index}",
                {
                    before.variable_id: 1,
                    after.variable_id: -1,
                    allocation_id: -1,
                },
                ConstraintRelation.EQUAL,
                0,
            )
            self._current[before.holding] = after
            self._allocation_variables[
                (event.process_id, process_input.input_id, before.holding)
            ] = allocation_id
            allocation_ids.append(allocation_id)
        self._system.add_constraint(
            f"{event.process_id}:{process_input.input_id}:allocation-total",
            {
                **{allocation_id: 1 for allocation_id in allocation_ids},
                flow_id: -1,
            },
            ConstraintRelation.EQUAL,
            0,
        )
        return flow_id

    def _compile_output(
        self,
        event: ProcessEvent,
        output: ProcessOutput,
        input_variables: dict[str, str],
    ) -> None:
        if isinstance(output.amount, FromInput):
            flow_id = input_variables[output.amount.input_id]
            variable = next(
                variable
                for variable in self._system.variables
                if variable.variable_id == flow_id
            )
            if variable.unit != output.holding.unit:
                raise ValueError("linked process input/output units differ")
            if variable.domain != output.domain:
                raise ValueError("linked process input/output domains differ")
        else:
            _validate_amount(output.domain, output.amount.amount, "output amount")
            flow_id = f"output:{event.process_id}:{output.output_id}"
            self._add_variable(
                flow_id,
                output.holding.unit,
                output.domain,
                f"output[{event.process_id}.{output.output_id}]",
            )
            self._system.add_constraint(
                f"{event.process_id}:{output.output_id}:amount",
                {flow_id: 1},
                ConstraintRelation.EQUAL,
                output.amount.amount,
            )

        before = self._current.get(output.holding)
        after = self._new_state(output.holding, output.domain)
        coefficients = {after.variable_id: 1, flow_id: -1}
        if before is not None:
            if before.domain != output.domain:
                raise ValueError("process output domain differs from holding state")
            coefficients[before.variable_id] = -1
        self._system.add_constraint(
            f"{event.process_id}:{output.output_id}:destination",
            coefficients,
            ConstraintRelation.EQUAL,
            0,
        )
        self._current[output.holding] = after

    def _compile_sink(
        self,
        event: ProcessEvent,
        sink: ProcessSink,
        input_variables: dict[str, str],
    ) -> None:
        input_variable_id = input_variables[sink.amount.input_id]
        input_variable = next(
            variable
            for variable in self._system.variables
            if variable.variable_id == input_variable_id
        )
        if input_variable.unit != sink.unit:
            raise ValueError("linked process input/sink units differ")
        if input_variable.domain != sink.domain:
            raise ValueError("linked process input/sink domains differ")
        sink_variable_id = f"sink:{event.process_id}:{sink.sink_id}"
        self._add_variable(
            sink_variable_id,
            sink.unit,
            sink.domain,
            f"sink[{event.process_id}.{sink.sink_id}:{sink.kind}]",
        )
        self._system.add_constraint(
            f"{event.process_id}:{sink.sink_id}:sink",
            {sink_variable_id: 1, input_variable_id: -1},
            ConstraintRelation.EQUAL,
            0,
        )

    def _new_state(
        self,
        holding: HoldingKey,
        domain: QuantityDomain,
    ) -> HoldingState:
        revision = self._revisions.get(holding, -1) + 1
        self._revisions[holding] = revision
        variable_id = (
            f"state:{holding.batch_id}:{holding.location_id}:"
            f"{holding.unit}:{holding.packaging_configuration_id or '-'}:r{revision}"
        )
        self._add_variable(
            variable_id,
            holding.unit,
            domain,
            f"state[{_holding_label(holding)} #{revision}]",
        )
        return HoldingState(holding, domain, revision, variable_id)

    def _add_variable(
        self,
        variable_id: str,
        unit: str,
        domain: QuantityDomain,
        label: str,
    ) -> None:
        self._system.add_variable(QuantityVariable(variable_id, unit, domain))
        self._labels[variable_id] = label


def _event_id(event: QuantityEvent) -> str:
    if isinstance(event, ProcessEvent):
        return event.process_id
    return event.event_id


def _holding_label(holding: HoldingKey) -> str:
    label = f"{holding.batch_id} @ {holding.location_id}"
    if holding.packaging_configuration_id is not None:
        label += f" / {holding.packaging_configuration_id}"
    return label


def _require_compatible(
    states: Sequence[HoldingState],
    subject: str,
    *,
    require_batch: bool,
) -> None:
    if not states:
        raise ValueError(f"{subject} needs at least one state")
    first = states[0]
    signature = (
        first.holding.unit,
        first.holding.packaging_configuration_id,
        first.domain,
    )
    if require_batch:
        signature = (first.holding.batch_id, *signature)
    for state in states[1:]:
        candidate = (
            state.holding.unit,
            state.holding.packaging_configuration_id,
            state.domain,
        )
        if require_batch:
            candidate = (state.holding.batch_id, *candidate)
        if candidate != signature:
            raise ValueError(
                f"{subject} must use compatible units, package configurations, "
                "and numeric domains"
            )


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


def _validate_amount(
    domain: QuantityDomain,
    amount: Fraction,
    field: str,
) -> None:
    if amount <= 0:
        raise ValueError(f"{field} must be positive")
    if domain == QuantityDomain.DISCRETE and amount.denominator != 1:
        raise ValueError(f"discrete {field} must be a whole amount")


def _render_fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _render_constraint(
    constraint: LinearConstraint,
    labels: dict[str, str],
) -> str:
    terms = []
    for variable_id, coefficient in constraint.coefficients:
        label = labels.get(variable_id, variable_id)
        magnitude = abs(coefficient)
        rendered = label
        if magnitude != 1:
            rendered = f"{_render_fraction(magnitude)}*{rendered}"
        if not terms:
            terms.append(f"-{rendered}" if coefficient < 0 else rendered)
        else:
            terms.append(f" {'-' if coefficient < 0 else '+'} {rendered}")
    relation = {
        ConstraintRelation.EQUAL: "=",
        ConstraintRelation.AT_LEAST: ">=",
        ConstraintRelation.AT_MOST: "<=",
    }[constraint.relation]
    return (
        f"{constraint.constraint_id}: {''.join(terms)} {relation} "
        f"{_render_fraction(constraint.bound)}"
    )
