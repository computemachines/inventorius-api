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
from itertools import groupby
from typing import Callable, Sequence

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
    """Reference one compiled input flow.

    A ``ProcessOutput`` using this amount preserves the input Batch identity;
    a ``ProcessSink`` using it sends the same flow beyond tracked holdings.
    """

    input_id: str

    def __post_init__(self) -> None:
        _nonblank(self.input_id, "input_id")


@dataclass(frozen=True)
class DeclaredOneToOneTransformation:
    """A caller-declared one-input-unit to one-output-unit transformation."""

    source_sku_id: str
    output_sku_id: str
    unit: str
    domain: QuantityDomain

    def __post_init__(self) -> None:
        _nonblank(self.source_sku_id, "source_sku_id")
        _nonblank(self.output_sku_id, "output_sku_id")
        _nonblank(self.unit, "unit")
        if self.source_sku_id == self.output_sku_id:
            raise ValueError("one-to-one transformation needs two distinct SKUs")
        if not isinstance(self.domain, QuantityDomain):
            raise ValueError("transformation domain must be a QuantityDomain")


@dataclass(frozen=True)
class OneToOneTransformedFromInput:
    """Create one new Batch under a declared one-to-one transformation."""

    input_id: str
    transformation: DeclaredOneToOneTransformation

    def __post_init__(self) -> None:
        _nonblank(self.input_id, "input_id")
        if not isinstance(
            self.transformation,
            DeclaredOneToOneTransformation,
        ):
            raise ValueError(
                "transformed input needs a DeclaredOneToOneTransformation"
            )


@dataclass(frozen=True)
class FromSource:
    """Produce exactly the quantity admitted through one external boundary."""

    source_id: str

    def __post_init__(self) -> None:
        _nonblank(self.source_id, "source_id")


@dataclass(frozen=True)
class CandidateSelection:
    """The observed SKU/location query behind an unresolved Batch choice.

    The enclosing ``ProcessInput.candidates`` preserves what the recorder could
    identify at the time. A knowledge-aware resolver may later return a
    different set without rewriting the physical observation into an arbitrary
    Batch fact.
    """

    selection_id: str
    sku_id: str
    location_id: str
    unit: str
    packaging_configuration_id: str | None = None

    def __post_init__(self) -> None:
        _nonblank(self.selection_id, "selection_id")
        _nonblank(self.sku_id, "sku_id")
        _nonblank(self.location_id, "location_id")
        _nonblank(self.unit, "unit")
InputAmount = ExactAmount | AllRemaining
OutputAmount = (
    ExactAmount | FromInput | OneToOneTransformedFromInput | FromSource
)

CandidateResolver = Callable[
    [CandidateSelection, tuple[HoldingKey, ...], datetime, datetime | None],
    Sequence[HoldingKey],
]


@dataclass(frozen=True)
class ProcessInput:
    """A quantity consumed from one holding or an unresolved candidate set."""

    input_id: str
    candidates: tuple[HoldingKey, ...]
    amount: InputAmount
    role: str = "input"
    selector: CandidateSelection | None = None
    structurally_contributes_to: tuple[str, ...] = ()

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
        if len(self.candidates) > 1 and self.selector is None:
            raise ValueError("ambiguous input needs its observed selection")
        if self.selector is not None:
            if not isinstance(self.selector, CandidateSelection):
                raise ValueError("selector must be a CandidateSelection")
            for holding in self.candidates:
                if (
                    holding.location_id != self.selector.location_id
                    or holding.unit != self.selector.unit
                    or holding.packaging_configuration_id
                    != self.selector.packaging_configuration_id
                ):
                    raise ValueError(
                        "input candidates must match the selection location, "
                        "unit, and package configuration"
                    )
        if len(set(self.structurally_contributes_to)) != len(
            self.structurally_contributes_to
        ):
            raise ValueError(
                "structural output identifiers must be distinct"
            )
        for output_id in self.structurally_contributes_to:
            _nonblank(output_id, "structural output identifier")


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
        if not isinstance(
            self.amount,
            (
                ExactAmount,
                FromInput,
                OneToOneTransformedFromInput,
                FromSource,
            ),
        ):
            raise ValueError("process output amount has an unsupported type")


@dataclass(frozen=True)
class PreservedIdentityOutput:
    """Move each possible source Batch allocation to a new location."""

    output_id: str
    input_id: str
    destination_location_id: str
    role: str = "output"

    def __post_init__(self) -> None:
        _nonblank(self.output_id, "output_id")
        _nonblank(self.input_id, "input_id")
        _nonblank(self.destination_location_id, "destination_location_id")
        _nonblank(self.role, "role")


@dataclass(frozen=True)
class ProcessSource:
    """A named external boundary admitting quantity into tracked holdings."""

    source_id: str
    kind: str
    unit: str
    domain: QuantityDomain
    observation: QuantityObservation
    note: str = ""

    def __post_init__(self) -> None:
        _nonblank(self.source_id, "source_id")
        _nonblank(self.kind, "kind")
        _nonblank(self.unit, "unit")
        if not isinstance(self.domain, QuantityDomain):
            raise ValueError("process source domain must be a QuantityDomain")
        if not isinstance(self.observation, QuantityObservation):
            raise ValueError("process source needs a quantity observation")
        _validate_observation(self.domain, self.observation)


@dataclass(frozen=True)
class BatchReplacement:
    """Replace one Batch identity everywhere it is held at this point in time."""

    replacement_id: str
    source_batch_id: str
    destination_batch_id: str

    def __post_init__(self) -> None:
        _nonblank(self.replacement_id, "replacement_id")
        _nonblank(self.source_batch_id, "source_batch_id")
        _nonblank(self.destination_batch_id, "destination_batch_id")
        if self.source_batch_id == self.destination_batch_id:
            raise ValueError("a Batch replacement needs two distinct identities")


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
    preserved_outputs: tuple[PreservedIdentityOutput, ...] = ()
    sinks: tuple[ProcessSink, ...] = ()
    sources: tuple[ProcessSource, ...] = ()
    batch_replacements: tuple[BatchReplacement, ...] = ()
    note: str = ""
    effective_order: int = 0

    def __post_init__(self) -> None:
        _nonblank(self.process_id, "process_id")
        _nonblank(self.kind, "kind")
        occurred = _aware(self.occurred_at, "occurred_at")
        recorded = _aware(self.recorded_at, "recorded_at")
        if recorded < occurred:
            raise ValueError("recorded_at cannot precede occurred_at")
        if (
            isinstance(self.effective_order, bool)
            or not isinstance(self.effective_order, int)
            or self.effective_order < 0
        ):
            raise ValueError("effective_order must be a nonnegative integer")
        if not self.inputs and not self.sources and not self.batch_replacements:
            raise ValueError(
                "output-only processes need explicit external-source semantics"
            )
        if self.batch_replacements and (
            self.inputs
            or self.outputs
            or self.preserved_outputs
            or self.sinks
            or self.sources
        ):
            raise ValueError(
                "Batch replacement is an exclusive semantic process in this slice"
            )
        if len(self.batch_replacements) > 1:
            raise ValueError("one process may replace only one Batch in this slice")
        input_ids = [item.input_id for item in self.inputs]
        output_ids = [item.output_id for item in self.outputs] + [
            item.output_id for item in self.preserved_outputs
        ]
        sink_ids = [item.sink_id for item in self.sinks]
        source_ids = [item.source_id for item in self.sources]
        if len(set(input_ids)) != len(input_ids):
            raise ValueError("process input identifiers must be distinct")
        if len(set(output_ids)) != len(output_ids):
            raise ValueError("process output identifiers must be distinct")
        if len(set(sink_ids)) != len(sink_ids):
            raise ValueError("process sink identifiers must be distinct")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("process source identifiers must be distinct")
        known_inputs = set(input_ids)
        transformed_outputs = [
            output
            for output in self.outputs
            if isinstance(output.amount, OneToOneTransformedFromInput)
        ]
        if transformed_outputs:
            if (
                len(transformed_outputs) != 1
                or len(self.inputs) != 1
                or len(self.outputs) != 1
                or self.preserved_outputs
                or self.sinks
                or self.sources
            ):
                raise ValueError(
                    "one-to-one transformation currently requires exactly one "
                    "input leg and one output"
                )
            transformed_output = transformed_outputs[0]
            transformed_input = self.inputs[0]
            if not isinstance(
                transformed_output.amount,
                OneToOneTransformedFromInput,
            ):
                raise ValueError("one-to-one transformation output is invalid")
            if transformed_output.amount.input_id != transformed_input.input_id:
                raise ValueError(
                    "transformed output must reference the process's one input"
                )
            if not isinstance(transformed_input.amount, ExactAmount):
                raise ValueError(
                    "one-to-one transformation currently requires an exact input"
                )
            if transformed_input.structurally_contributes_to:
                raise ValueError(
                    "one-to-one transformation cannot also be structural provenance"
                )
        for output in self.preserved_outputs:
            if output.input_id not in known_inputs:
                raise ValueError("preserved output references an unknown input")
            process_input = next(
                item for item in self.inputs if item.input_id == output.input_id
            )
            if process_input.selector is None:
                raise ValueError(
                    "preserved candidate output needs an observed selection"
                )
            if any(
                holding.location_id == output.destination_location_id
                for holding in process_input.candidates
            ):
                raise ValueError(
                    "preserved output destination must differ from its sources"
                )
        for output in self.outputs:
            if (
                isinstance(
                    output.amount,
                    (FromInput, OneToOneTransformedFromInput),
                )
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
                        "an ambiguous input needs an explicit one-to-one "
                        "transformation or preserved candidate outputs"
                    )
                if source.candidates[0].batch_id != output.holding.batch_id:
                    raise ValueError(
                        "FromInput must preserve its input Batch; use "
                        "OneToOneTransformedFromInput to create a new Batch"
                    )
            if isinstance(output.amount, OneToOneTransformedFromInput):
                source = next(
                    item
                    for item in self.inputs
                    if item.input_id == output.amount.input_id
                )
                transformation = output.amount.transformation
                if output.holding.batch_id in {
                    holding.batch_id for holding in source.candidates
                }:
                    raise ValueError(
                        "a one-to-one transformation must create a new Batch"
                    )
                if output.holding.unit != transformation.unit:
                    raise ValueError(
                        "transformed output unit differs from its declaration"
                    )
                if output.domain != transformation.domain:
                    raise ValueError(
                        "transformed output domain differs from its declaration"
                    )
                if any(
                    holding.unit != transformation.unit
                    for holding in source.candidates
                ):
                    raise ValueError(
                        "transformed input unit differs from its declaration"
                    )
                if (
                    source.selector is not None
                    and source.selector.sku_id
                    != transformation.source_sku_id
                ):
                    raise ValueError(
                        "transformed input selector differs from its declared "
                        "source SKU"
                    )
            if (
                isinstance(output.amount, FromSource)
                and output.amount.source_id not in set(source_ids)
            ):
                raise ValueError("process output references an unknown source")
        for sink in self.sinks:
            if sink.amount.input_id not in known_inputs:
                raise ValueError("process sink references an unknown input")
        known_outputs = set(output_ids)
        for process_input in self.inputs:
            unknown = (
                set(process_input.structurally_contributes_to) - known_outputs
            )
            if unknown:
                raise ValueError(
                    "process input structurally contributes to an unknown output"
                )
            quantity_destinations = sum(
                isinstance(
                    output.amount,
                    (FromInput, OneToOneTransformedFromInput),
                )
                and output.amount.input_id == process_input.input_id
                for output in self.outputs
            ) + sum(
                sink.amount.input_id == process_input.input_id
                for sink in self.sinks
            ) + sum(
                output.input_id == process_input.input_id
                for output in self.preserved_outputs
            )
            if quantity_destinations > 1:
                raise ValueError(
                    "a process input cannot feed multiple quantity destinations "
                    "without explicit split allocation"
                )
            if (
                quantity_destinations == 0
                and not process_input.structurally_contributes_to
            ):
                raise ValueError(
                    "every process input needs an output, sink, or structural "
                    "contribution"
                )
        for source_id in source_ids:
            references = [
                output
                for output in self.outputs
                if isinstance(output.amount, FromSource)
                and output.amount.source_id == source_id
            ]
            if len(references) != 1:
                raise ValueError(
                    "each external source must feed exactly one output in this slice"
                )
        if not self.inputs and self.sources and any(
            not isinstance(output.amount, FromSource)
            for output in self.outputs
        ):
            raise ValueError(
                "every output of an inputless process must reference an "
                "external source"
            )
        touched_inputs = [
            holding for item in self.inputs for holding in item.candidates
        ]
        touched_outputs = [item.holding for item in self.outputs] + [
            HoldingKey(
                holding.batch_id,
                output.destination_location_id,
                holding.unit,
                holding.packaging_configuration_id,
            )
            for output in self.preserved_outputs
            for process_input in self.inputs
            if process_input.input_id == output.input_id
            for holding in process_input.candidates
        ]
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
    effective_order: int = 0

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
        if (
            isinstance(self.effective_order, bool)
            or not isinstance(self.effective_order, int)
            or self.effective_order < 0
        ):
            raise ValueError("effective_order must be a nonnegative integer")

    @property
    def event_id(self) -> str:
        return self.observation.observation_id


QuantityEvent = ProcessEvent | ObservationEvent


@dataclass(frozen=True)
class _EventTouches:
    """Concrete holdings and whole-Batch identities touched by one event."""

    holdings: frozenset[HoldingKey]
    whole_batch_ids: frozenset[str]

    @property
    def holding_batch_ids(self) -> frozenset[str]:
        return frozenset(holding.batch_id for holding in self.holdings)

    def overlaps(self, other: _EventTouches) -> bool:
        return bool(
            self.holdings & other.holdings
            or self.whole_batch_ids & other.holding_batch_ids
            or other.whole_batch_ids & self.holding_batch_ids
            or self.whole_batch_ids & other.whole_batch_ids
        )


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
        candidate_resolver: CandidateResolver | None = None,
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
                event.effective_order,
                _event_id(event),
            )
        )
        return _ProcessCompiler(
            self._query_timeout_ms,
            known_at=known_at,
            candidate_resolver=candidate_resolver,
        ).compile(events)


class CompiledProcessQuantities:
    """One disposable solver projection of the recorded process timeline."""

    def __init__(
        self,
        system: QuantityConstraintSystem,
        current: dict[HoldingKey, HoldingState],
        input_variables: dict[tuple[str, str], str],
        allocation_variables: dict[tuple[str, str, HoldingKey], str],
        output_source_allocation_variables: dict[
            tuple[str, str, HoldingKey], str
        ],
        source_variables: dict[tuple[str, str], str],
        replacement_holdings: dict[str, tuple[tuple[HoldingKey, HoldingKey], ...]],
        labels: dict[str, str],
        event_order: tuple[str, ...],
    ) -> None:
        self._system = system
        self._current = current
        self._input_variables = input_variables
        self._allocation_variables = allocation_variables
        self._output_source_allocation_variables = (
            output_source_allocation_variables
        )
        self._source_variables = source_variables
        self._replacement_holdings = replacement_holdings
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

    def output_source_allocation_bounds(
        self,
        process_id: str,
        output_id: str,
        source_holding: HoldingKey,
    ) -> QuantityBounds:
        """Bound one source holding's allocation into a transformed output."""

        try:
            variable_id = self._output_source_allocation_variables[
                (process_id, output_id, source_holding)
            ]
        except KeyError as error:
            raise ValueError(
                "process output has no source allocation from that holding"
            ) from error
        return self._system.bounds(variable_id)

    def output_source_allocation_total_bounds(
        self,
        process_id: str,
        output_id: str,
        source_holdings: Sequence[HoldingKey],
    ) -> QuantityBounds:
        """Bound a correlated total over several output source allocations."""

        selected = tuple(source_holdings)
        if not selected:
            raise ValueError(
                "an output source allocation total needs a source holding"
            )
        if len(set(selected)) != len(selected):
            raise ValueError(
                "an output source allocation total needs distinct source holdings"
            )
        try:
            variable_ids = [
                self._output_source_allocation_variables[
                    (process_id, output_id, holding)
                ]
                for holding in selected
            ]
        except KeyError as error:
            raise ValueError(
                "process output has no source allocation from one selected holding"
            ) from error
        return self._system.expression_bounds(
            {variable_id: 1 for variable_id in variable_ids}
        )

    def source_bounds(self, process_id: str, source_id: str) -> QuantityBounds:
        try:
            variable_id = self._source_variables[(process_id, source_id)]
        except KeyError as error:
            raise ValueError("process source has no compiled quantity") from error
        return self._system.bounds(variable_id)

    def replacement_holdings(
        self,
        process_id: str,
    ) -> tuple[tuple[HoldingKey, HoldingKey], ...]:
        try:
            return self._replacement_holdings[process_id]
        except KeyError as error:
            raise ValueError("process has no compiled Batch replacement") from error

    def rendered_constraints(self) -> tuple[str, ...]:
        """Return readable algebra without exposing generated Z3 expressions."""

        return tuple(
            _render_constraint(constraint, self._labels)
            for constraint in self._system.constraints
            if not constraint.constraint_id.startswith("domain:")
        )


class _ProcessCompiler:
    def __init__(
        self,
        timeout_ms: int,
        *,
        known_at: datetime | None,
        candidate_resolver: CandidateResolver | None,
    ) -> None:
        self._system = QuantityConstraintSystem(timeout_ms=timeout_ms)
        self._current: dict[HoldingKey, HoldingState] = {}
        self._revisions: dict[HoldingKey, int] = {}
        self._input_variables: dict[tuple[str, str], str] = {}
        self._allocation_variables: dict[
            tuple[str, str, HoldingKey], str
        ] = {}
        self._output_source_allocation_variables: dict[
            tuple[str, str, HoldingKey], str
        ] = {}
        self._input_candidate_variables: dict[
            tuple[str, str, HoldingKey], str
        ] = {}
        self._source_variables: dict[tuple[str, str], str] = {}
        self._replacement_holdings: dict[
            str, tuple[tuple[HoldingKey, HoldingKey], ...]
        ] = {}
        self._labels: dict[str, str] = {}
        self._next_state_index = 0
        self._known_at = known_at
        self._candidate_resolver = candidate_resolver

    def compile(
        self,
        events: Sequence[QuantityEvent],
    ) -> CompiledProcessQuantities:
        order = []
        for _, simultaneous in groupby(
            events,
            key=lambda event: (event.occurred_at, event.effective_order),
        ):
            group = tuple(simultaneous)
            resolved = self._resolve_group_candidates(group)
            self._validate_resolved_process_shapes(group, resolved)
            self._reject_overlapping_simultaneous_events(group, resolved)
            for event in group:
                order.append(_event_id(event))
                if isinstance(event, ObservationEvent):
                    self._compile_observation(event)
                else:
                    self._compile_process(event, resolved)
        return CompiledProcessQuantities(
            self._system,
            dict(self._current),
            dict(self._input_variables),
            dict(self._allocation_variables),
            dict(self._output_source_allocation_variables),
            dict(self._source_variables),
            dict(self._replacement_holdings),
            dict(self._labels),
            tuple(order),
        )

    def _resolve_group_candidates(
        self,
        events: Sequence[QuantityEvent],
    ) -> dict[tuple[str, str], tuple[HoldingKey, ...]]:
        resolved: dict[tuple[str, str], tuple[HoldingKey, ...]] = {}
        for event in events:
            if not isinstance(event, ProcessEvent):
                continue
            for process_input in event.inputs:
                candidates: Sequence[HoldingKey] = process_input.candidates
                if (
                    process_input.selector is not None
                    and self._candidate_resolver is not None
                ):
                    candidates = self._candidate_resolver(
                        process_input.selector,
                        process_input.candidates,
                        event.occurred_at,
                        self._known_at,
                    )
                normalized = tuple(candidates)
                if not normalized:
                    raise ValueError("candidate resolver returned no holdings")
                if len(set(normalized)) != len(normalized):
                    raise ValueError("candidate resolver returned duplicate holdings")
                selector = process_input.selector
                if selector is not None:
                    for holding in normalized:
                        if (
                            holding.location_id != selector.location_id
                            or holding.unit != selector.unit
                            or holding.packaging_configuration_id
                            != selector.packaging_configuration_id
                        ):
                            raise ValueError(
                                "resolved candidates must match the observed "
                                "selection location, unit, and package configuration"
                            )
                if (
                    isinstance(process_input.amount, AllRemaining)
                    and len(normalized) != 1
                ):
                    raise ValueError(
                        "all remaining requires one resolved exact holding"
                    )
                resolved[(event.process_id, process_input.input_id)] = normalized
        return resolved

    @staticmethod
    def _validate_resolved_process_shapes(
        events: Sequence[QuantityEvent],
        resolved: dict[tuple[str, str], tuple[HoldingKey, ...]],
    ) -> None:
        """Recheck holding collisions after knowledge-aware candidate lookup."""

        for event in events:
            if not isinstance(event, ProcessEvent) or event.batch_replacements:
                continue
            touched_inputs = [
                holding
                for process_input in event.inputs
                for holding in resolved[
                    (event.process_id, process_input.input_id)
                ]
            ]
            touched_outputs = [output.holding for output in event.outputs]
            touched_outputs.extend(
                HoldingKey(
                    source.batch_id,
                    output.destination_location_id,
                    source.unit,
                    source.packaging_configuration_id,
                )
                for output in event.preserved_outputs
                for source in resolved[(event.process_id, output.input_id)]
            )
            if len(set(touched_inputs)) != len(touched_inputs):
                raise ValueError(
                    "resolved process inputs cannot consume a holding twice"
                )
            if len(set(touched_outputs)) != len(touched_outputs):
                raise ValueError(
                    "resolved process outputs cannot produce into a holding twice"
                )
            if set(touched_inputs) & set(touched_outputs):
                raise ValueError(
                    "same-holding input/output semantics are not defined yet"
                )

    def _reject_overlapping_simultaneous_events(
        self,
        events: Sequence[QuantityEvent],
        resolved: dict[tuple[str, str], tuple[HoldingKey, ...]],
    ) -> None:
        touched: list[tuple[str, _EventTouches]] = []
        for event in events:
            if isinstance(event, ObservationEvent):
                holdings = {event.holding}
                whole_batch_ids: set[str] = set()
            else:
                holdings = {
                    holding
                    for process_input in event.inputs
                    for holding in resolved[
                        (event.process_id, process_input.input_id)
                    ]
                }
                holdings.update(output.holding for output in event.outputs)
                for output in event.preserved_outputs:
                    for source in resolved[(event.process_id, output.input_id)]:
                        holdings.add(HoldingKey(
                            source.batch_id,
                            output.destination_location_id,
                            source.unit,
                            source.packaging_configuration_id,
                        ))
                whole_batch_ids = {
                    batch_id
                    for replacement in event.batch_replacements
                    for batch_id in (
                        replacement.source_batch_id,
                        replacement.destination_batch_id,
                    )
                }
                whole_batch_ids.update(
                    output.holding.batch_id
                    for output in event.outputs
                    if isinstance(
                        output.amount,
                        OneToOneTransformedFromInput,
                    )
                )
            event_touches = _EventTouches(
                frozenset(holdings),
                frozenset(whole_batch_ids),
            )
            for prior_id, prior_touches in touched:
                if event_touches.overlaps(prior_touches):
                    raise ValueError(
                        "events sharing occurred_at and effective_order overlap "
                        "on a holding or whole-Batch identity: "
                        f"{prior_id}, {_event_id(event)}"
                    )
            touched.append((_event_id(event), event_touches))

    def _compile_observation(self, event: ObservationEvent) -> None:
        state = self._current.get(event.holding)
        if state is None:
            state = self._new_state(event.holding, event.domain)
            self._current[event.holding] = state
        elif state.domain != event.domain:
            raise ValueError("observation domain does not match holding state")
        _validate_observation(event.domain, event.observation)
        _add_observation_constraints(
            self._system,
            event.observation,
            state.variable_id,
            event.event_id,
        )

    def _compile_process(
        self,
        event: ProcessEvent,
        resolved_candidates: dict[tuple[str, str], tuple[HoldingKey, ...]],
    ) -> None:
        if event.batch_replacements:
            self._compile_batch_replacement(event, event.batch_replacements[0])
            return
        for output in event.outputs:
            if isinstance(output.amount, FromInput):
                candidates = resolved_candidates[
                    (event.process_id, output.amount.input_id)
                ]
                if len(candidates) > 1:
                    raise ValueError(
                        "a resolved ambiguous input needs an explicit one-to-one "
                        "transformation or preserved candidate outputs"
                    )
                if candidates[0].batch_id != output.holding.batch_id:
                    raise ValueError(
                        "FromInput must preserve its resolved input Batch"
                    )
            if isinstance(output.amount, OneToOneTransformedFromInput):
                candidates = resolved_candidates[
                    (event.process_id, output.amount.input_id)
                ]
                if output.holding.batch_id in {
                    holding.batch_id for holding in candidates
                }:
                    raise ValueError(
                        "a one-to-one transformation must create a new Batch"
                    )
                if any(
                    holding.batch_id == output.holding.batch_id
                    for holding in self._current
                ):
                    raise ValueError(
                        "one-to-one transformation output Batch already exists"
                    )
        input_variables: dict[str, str] = {}
        for process_input in event.inputs:
            variable_id = self._compile_input(
                event,
                process_input,
                resolved_candidates[(event.process_id, process_input.input_id)],
            )
            input_variables[process_input.input_id] = variable_id
        source_variables = {
            source.source_id: self._compile_source(event, source)
            for source in event.sources
        }
        for output in event.outputs:
            self._compile_output(
                event,
                output,
                input_variables,
                source_variables,
                resolved_candidates,
            )
        for output in event.preserved_outputs:
            self._compile_preserved_output(
                event,
                output,
                resolved_candidates[(event.process_id, output.input_id)],
            )
        for sink in event.sinks:
            self._compile_sink(event, sink, input_variables)

    def _compile_input(
        self,
        event: ProcessEvent,
        process_input: ProcessInput,
        candidates: tuple[HoldingKey, ...],
    ) -> str:
        before_states = []
        for holding in candidates:
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
            self._input_candidate_variables[
                (event.process_id, process_input.input_id, before.holding)
            ] = flow_id
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
            self._input_candidate_variables[
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
        source_variables: dict[str, str],
        resolved_candidates: dict[
            tuple[str, str], tuple[HoldingKey, ...]
        ],
    ) -> None:
        if isinstance(output.amount, OneToOneTransformedFromInput):
            flow_id = self._compile_transformed_output_flow(
                event,
                output,
                input_variables,
                resolved_candidates[
                    (event.process_id, output.amount.input_id)
                ],
            )
        elif isinstance(output.amount, FromInput):
            flow_id = input_variables[output.amount.input_id]
        elif isinstance(output.amount, FromSource):
            flow_id = source_variables[output.amount.source_id]
        else:
            flow_id = ""
        if isinstance(output.amount, (FromInput, FromSource)):
            variable = next(
                variable
                for variable in self._system.variables
                if variable.variable_id == flow_id
            )
            if variable.unit != output.holding.unit:
                raise ValueError("linked process input/output units differ")
            if variable.domain != output.domain:
                raise ValueError("linked process input/output domains differ")
        elif isinstance(output.amount, OneToOneTransformedFromInput):
            pass
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

    def _compile_transformed_output_flow(
        self,
        event: ProcessEvent,
        output: ProcessOutput,
        input_variables: dict[str, str],
        candidates: tuple[HoldingKey, ...],
    ) -> str:
        amount = output.amount
        if not isinstance(amount, OneToOneTransformedFromInput):
            raise ValueError("one-to-one transformation output is invalid")
        transformation = amount.transformation
        input_flow_id = input_variables[amount.input_id]
        input_variable = next(
            variable
            for variable in self._system.variables
            if variable.variable_id == input_flow_id
        )
        if input_variable.unit != transformation.unit:
            raise ValueError(
                "transformed input flow unit differs from its declaration"
            )
        if input_variable.domain != transformation.domain:
            raise ValueError(
                "transformed input flow domain differs from its declaration"
            )

        output_flow_id = f"output:{event.process_id}:{output.output_id}"
        self._add_variable(
            output_flow_id,
            transformation.unit,
            transformation.domain,
            f"output[{event.process_id}.{output.output_id}]",
        )
        self._system.add_constraint(
            f"{event.process_id}:{output.output_id}:one-to-one",
            {output_flow_id: 1, input_flow_id: -1},
            ConstraintRelation.EQUAL,
            0,
        )

        for index, source_holding in enumerate(candidates):
            input_candidate_id = self._input_candidate_variables[
                (event.process_id, amount.input_id, source_holding)
            ]
            source_allocation_id = (
                "output-source-allocation:"
                f"{event.process_id}:{output.output_id}:{index}"
            )
            self._add_variable(
                source_allocation_id,
                transformation.unit,
                transformation.domain,
                (
                    f"output-source-allocation[{_holding_label(source_holding)} -> "
                    f"{event.process_id}.{output.output_id}]"
                ),
            )
            self._system.add_constraint(
                (
                    f"{event.process_id}:{output.output_id}:"
                    f"source-allocation:{index}"
                ),
                {source_allocation_id: 1, input_candidate_id: -1},
                ConstraintRelation.EQUAL,
                0,
            )
            self._output_source_allocation_variables[
                (event.process_id, output.output_id, source_holding)
            ] = source_allocation_id
        return output_flow_id

    def _compile_preserved_output(
        self,
        event: ProcessEvent,
        output: PreservedIdentityOutput,
        candidates: tuple[HoldingKey, ...],
    ) -> None:
        for index, source in enumerate(candidates):
            flow_id = self._input_candidate_variables[
                (event.process_id, output.input_id, source)
            ]
            source_state = self._current[source]
            destination = HoldingKey(
                source.batch_id,
                output.destination_location_id,
                source.unit,
                source.packaging_configuration_id,
            )
            before = self._current.get(destination)
            after = self._new_state(destination, source_state.domain)
            coefficients = {after.variable_id: 1, flow_id: -1}
            if before is not None:
                if before.domain != source_state.domain:
                    raise ValueError(
                        "preserved output domain differs from destination state"
                    )
                coefficients[before.variable_id] = -1
            self._system.add_constraint(
                f"{event.process_id}:{output.output_id}:destination:{index}",
                coefficients,
                ConstraintRelation.EQUAL,
                0,
            )
            self._current[destination] = after

    def _compile_source(
        self,
        event: ProcessEvent,
        source: ProcessSource,
    ) -> str:
        variable_id = f"source:{event.process_id}:{source.source_id}"
        self._add_variable(
            variable_id,
            source.unit,
            source.domain,
            f"source[{event.process_id}.{source.source_id}:{source.kind}]",
        )
        self._source_variables[(event.process_id, source.source_id)] = variable_id
        _add_observation_constraints(
            self._system,
            source.observation,
            variable_id,
            f"{event.process_id}:{source.source_id}",
        )
        return variable_id

    def _compile_batch_replacement(
        self,
        event: ProcessEvent,
        replacement: BatchReplacement,
    ) -> None:
        source_states = sorted(
            (
                state
                for holding, state in self._current.items()
                if holding.batch_id == replacement.source_batch_id
            ),
            key=lambda state: _holding_label(state.holding),
        )
        if not source_states:
            raise ValueError("Batch replacement source has no earlier holding state")
        mappings = []
        for index, before in enumerate(source_states):
            source_after = self._new_state(before.holding, before.domain)
            flow_id = f"replacement:{event.process_id}:{index}"
            self._add_variable(
                flow_id,
                before.holding.unit,
                before.domain,
                f"replacement[{event.process_id} <- {_holding_label(before.holding)}]",
            )
            self._system.add_constraint(
                f"{event.process_id}:{replacement.replacement_id}:source:{index}",
                {
                    before.variable_id: 1,
                    source_after.variable_id: -1,
                    flow_id: -1,
                },
                ConstraintRelation.EQUAL,
                0,
            )
            self._system.add_constraint(
                f"{event.process_id}:{replacement.replacement_id}:all:{index}",
                {source_after.variable_id: 1},
                ConstraintRelation.EQUAL,
                0,
            )
            self._current[before.holding] = source_after

            destination = HoldingKey(
                replacement.destination_batch_id,
                before.holding.location_id,
                before.holding.unit,
                before.holding.packaging_configuration_id,
            )
            destination_before = self._current.get(destination)
            destination_after = self._new_state(destination, before.domain)
            coefficients = {destination_after.variable_id: 1, flow_id: -1}
            if destination_before is not None:
                if destination_before.domain != before.domain:
                    raise ValueError(
                        "Batch replacement destination has a different domain"
                    )
                coefficients[destination_before.variable_id] = -1
            self._system.add_constraint(
                f"{event.process_id}:{replacement.replacement_id}:destination:{index}",
                coefficients,
                ConstraintRelation.EQUAL,
                0,
            )
            self._current[destination] = destination_after
            mappings.append((before.holding, destination))
        self._replacement_holdings[event.process_id] = tuple(mappings)

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
        state_index = self._next_state_index
        self._next_state_index += 1
        variable_id = f"state:{state_index}:r{revision}"
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


def _add_observation_constraints(
    system: QuantityConstraintSystem,
    observation: QuantityObservation,
    variable_id: str,
    constraint_prefix: str,
) -> None:
    if observation.lower is not None and observation.lower == observation.upper:
        system.add_constraint(
            f"{constraint_prefix}:exact",
            {variable_id: 1},
            ConstraintRelation.EQUAL,
            observation.lower,
        )
        return
    if observation.lower is not None:
        system.add_constraint(
            f"{constraint_prefix}:lower",
            {variable_id: 1},
            ConstraintRelation.AT_LEAST,
            observation.lower,
        )
    if observation.upper is not None:
        system.add_constraint(
            f"{constraint_prefix}:upper",
            {variable_id: 1},
            ConstraintRelation.AT_MOST,
            observation.upper,
        )


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
