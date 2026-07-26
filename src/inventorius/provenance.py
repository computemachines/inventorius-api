"""Small, persistence-free domain kernel for conserved provenance flows.

The first supported allocation semantic is intentionally narrow: inputs of one
unit are pooled and divided into outputs without recording their allocation.
The observations and conservation constraints are retained; contribution bounds
are calculated only when queried.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable


def _decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class Quantity:
    amount: Decimal
    unit: str

    def __init__(self, amount: Decimal | int | str, unit: str):
        amount = _decimal(amount)
        if amount <= 0:
            raise ValueError("quantity must be positive")
        if not unit:
            raise ValueError("quantity unit must not be empty")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "unit", unit)


@dataclass(frozen=True)
class HoldingReference:
    batch_id: str
    location_id: str


@dataclass(frozen=True)
class ConsumedHolding:
    holding: HoldingReference
    quantity: Quantity


@dataclass(frozen=True)
class ProducedHolding:
    batch_id: str
    location_id: str
    quantity: Quantity


@dataclass(frozen=True)
class MaterialLoss:
    """A conserved terminal output which is no longer held as inventory."""

    loss_id: str
    reason: str
    quantity: Quantity


@dataclass(frozen=True)
class ComponentUse:
    """A distinguishable input incorporated into an assembly output."""

    holding: HoldingReference
    quantity: Quantity
    role: str

    def __post_init__(self):
        if not self.role:
            raise ValueError("component role must not be empty")


class AllocationSemantics(str, Enum):
    """How input contributions are known to be distributed over outputs."""

    UNCERTAIN_CONSERVED_POOL = "uncertain-conserved-pool"
    HOMOGENEOUS_BLEND = "homogeneous-blend"


@dataclass(frozen=True)
class TransformationRun:
    run_id: str
    consumed: tuple[ConsumedHolding, ...]
    produced: tuple[ProducedHolding, ...]
    losses: tuple[MaterialLoss, ...] = ()
    allocation: AllocationSemantics = (
        AllocationSemantics.UNCERTAIN_CONSERVED_POOL
    )


@dataclass(frozen=True)
class AssemblyRun:
    """Exact component containment, deliberately outside pool arithmetic."""

    run_id: str
    components: tuple[ComponentUse, ...]
    produced: ProducedHolding


@dataclass(frozen=True)
class ContributionBounds:
    minimum: Decimal
    maximum: Decimal
    unit: str


class GeneralSolverRequired(NotImplementedError):
    """The retained constraints exceed the initial closed-form query engine."""


@dataclass
class _ResidualEdge:
    target: tuple[str, str]
    reverse_index: int
    capacity: Decimal


def _maximum_flow(
    edges: Iterable[
        tuple[tuple[str, str], tuple[str, str], Decimal]
    ],
    source: tuple[str, str],
    sink: tuple[str, str],
) -> Decimal:
    """Compute a small exact max flow using Decimal residual capacities."""

    graph: dict[tuple[str, str], list[_ResidualEdge]] = defaultdict(list)

    for start, end, capacity in edges:
        if capacity <= 0:
            continue
        forward = _ResidualEdge(end, len(graph[end]), capacity)
        reverse = _ResidualEdge(start, len(graph[start]), Decimal(0))
        graph[start].append(forward)
        graph[end].append(reverse)

    total = Decimal(0)
    while True:
        levels = {source: 0}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for edge in graph[node]:
                if edge.capacity > 0 and edge.target not in levels:
                    levels[edge.target] = levels[node] + 1
                    queue.append(edge.target)
        if sink not in levels:
            return total

        next_edge: dict[tuple[str, str], int] = defaultdict(int)

        def send(
            node: tuple[str, str],
            limit: Decimal,
        ) -> Decimal:
            if node == sink:
                return limit
            while next_edge[node] < len(graph[node]):
                edge = graph[node][next_edge[node]]
                if (
                    edge.capacity > 0
                    and levels.get(edge.target) == levels[node] + 1
                ):
                    pushed = send(edge.target, min(limit, edge.capacity))
                    if pushed > 0:
                        edge.capacity -= pushed
                        reverse = graph[edge.target][edge.reverse_index]
                        reverse.capacity += pushed
                        return pushed
                next_edge[node] += 1
            return Decimal(0)

        while True:
            pushed = send(source, Decimal("Infinity"))
            if pushed == 0:
                break
            total += pushed


class ProvenanceNetwork:
    """Records transformation observations and answers bounded lineage queries."""

    def __init__(self):
        self._runs: dict[str, TransformationRun] = {}
        self._assemblies: dict[str, AssemblyRun] = {}
        self._producer_by_output: dict[str, str] = {}
        self._output_quantity: dict[str, Quantity] = {}
        self._assembly_by_batch: dict[str, str] = {}

    def add_run(self, run: TransformationRun) -> None:
        if run.run_id in self._runs:
            raise ValueError(f"duplicate run: {run.run_id}")
        if not run.consumed or not run.produced:
            raise ValueError("a transformation needs inputs and outputs")

        units = {
            flow.quantity.unit
            for flow in (*run.consumed, *run.produced, *run.losses)
        }
        if len(units) != 1:
            raise ValueError("a conserved pool must use one compatible unit")

        consumed_total = sum(
            (flow.quantity.amount for flow in run.consumed), Decimal(0)
        )
        produced_total = sum(
            (flow.quantity.amount for flow in run.produced), Decimal(0)
        )
        loss_total = sum(
            (flow.quantity.amount for flow in run.losses), Decimal(0)
        )
        if consumed_total != produced_total + loss_total:
            raise ValueError("a conserved pool must preserve total quantity")

        output_ids = [flow.batch_id for flow in run.produced]
        output_ids.extend(flow.loss_id for flow in run.losses)
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("a run cannot produce the same output twice")
        for output_id in output_ids:
            if output_id in self._producer_by_output:
                raise ValueError(f"output already has a producer: {output_id}")

        self._runs[run.run_id] = run
        for flow in run.produced:
            self._producer_by_output[flow.batch_id] = run.run_id
            self._output_quantity[flow.batch_id] = flow.quantity
        for flow in run.losses:
            self._producer_by_output[flow.loss_id] = run.run_id
            self._output_quantity[flow.loss_id] = flow.quantity

    def add_assembly(self, run: AssemblyRun) -> None:
        """Record components without pretending their quantities are fungible."""

        if run.run_id in self._runs or run.run_id in self._assemblies:
            raise ValueError(f"duplicate run: {run.run_id}")
        if not run.components:
            raise ValueError("an assembly needs components")

        output_id = run.produced.batch_id
        if (
            output_id in self._producer_by_output
            or output_id in self._assembly_by_batch
        ):
            raise ValueError(f"output already has a producer: {output_id}")
        if any(
            component.holding.batch_id == output_id
            for component in run.components
        ):
            raise ValueError("an assembly cannot contain itself directly")

        units_by_batch: dict[str, set[str]] = defaultdict(set)
        for component in run.components:
            units_by_batch[component.holding.batch_id].add(
                component.quantity.unit
            )
        if any(len(units) != 1 for units in units_by_batch.values()):
            raise ValueError("one component batch cannot use incompatible units")

        self._assemblies[run.run_id] = run
        self._assembly_by_batch[output_id] = run.run_id

    def direct_component_bounds(
        self,
        source_batch_id: str,
        assembly_batch_id: str,
    ) -> ContributionBounds:
        """Return an exact direct component amount in the source's own unit."""

        run_id = self._assembly_by_batch.get(assembly_batch_id)
        if run_id is None:
            raise ValueError(
                f"batch has no recorded assembly: {assembly_batch_id}"
            )

        matches = [
            component
            for component in self._assemblies[run_id].components
            if component.holding.batch_id == source_batch_id
        ]
        if not matches:
            raise ValueError(
                f"batch is not a direct component: {source_batch_id}"
            )

        unit = matches[0].quantity.unit
        amount = sum(
            (component.quantity.amount for component in matches),
            Decimal(0),
        )
        return ContributionBounds(amount, amount, unit)

    def contribution_bounds(
        self,
        source_batch_id: str,
        target_output_ids: Iterable[str],
    ) -> ContributionBounds:
        """Bound one source batch's contribution to complete output records.

        The query groups sibling outputs before moving upstream. This preserves
        the correlation that makes a complete downstream recombination exact.
        A future general linear solver will handle paths whose upstream demand
        is itself a non-exact interval.
        """

        target_ids = tuple(dict.fromkeys(target_output_ids))
        if not target_ids:
            raise ValueError("at least one target output is required")

        pending: dict[str, Decimal] = {}
        query_unit: str | None = None
        for output_id in target_ids:
            quantity = self._output_quantity.get(output_id)
            if quantity is None:
                raise ValueError(
                    f"target output has no recorded producer: {output_id}"
                )
            if query_unit is None:
                query_unit = quantity.unit
            elif quantity.unit != query_unit:
                raise ValueError("target outputs use incompatible units")
            pending[output_id] = quantity.amount

        minimum = Decimal(0)
        maximum = Decimal(0)

        while pending:
            by_run: dict[str, dict[str, Decimal]] = defaultdict(dict)
            for output_id, amount in pending.items():
                run_id = self._producer_by_output.get(output_id)
                if run_id is None:
                    if output_id == source_batch_id:
                        minimum += amount
                        maximum += amount
                    continue
                by_run[run_id][output_id] = amount

            next_pending: dict[str, Decimal] = defaultdict(Decimal)
            for run_id, selected_outputs in by_run.items():
                run = self._runs[run_id]
                total = sum(
                    (flow.quantity.amount for flow in run.produced), Decimal(0)
                )
                total += sum(
                    (flow.quantity.amount for flow in run.losses), Decimal(0)
                )
                queried = sum(selected_outputs.values(), Decimal(0))

                inputs_by_batch: dict[str, Decimal] = defaultdict(Decimal)
                for flow in run.consumed:
                    inputs_by_batch[flow.holding.batch_id] += flow.quantity.amount

                for input_batch_id, input_amount in inputs_by_batch.items():
                    if run.allocation == AllocationSemantics.HOMOGENEOUS_BLEND:
                        contribution = input_amount * queried / total
                        lower = contribution
                        upper = contribution
                    else:
                        lower = max(Decimal(0), input_amount + queried - total)
                        upper = min(input_amount, queried)

                    if input_batch_id == source_batch_id:
                        minimum += lower
                        maximum += upper
                        continue
                    if input_batch_id not in self._producer_by_output or upper == 0:
                        continue
                    if lower != upper:
                        return self._global_uncertain_bounds(
                            source_batch_id,
                            target_ids,
                            query_unit,
                        )
                    next_pending[input_batch_id] += lower

            pending = dict(next_pending)

        assert query_unit is not None
        return ContributionBounds(minimum, maximum, query_unit)

    def _global_uncertain_bounds(
        self,
        source_batch_id: str,
        target_ids: tuple[str, ...],
        unit: str,
    ) -> ContributionBounds:
        """Optimize source flow globally across uncertain conserved pools."""

        relevant_runs = self._ancestor_run_ids(target_ids, source_batch_id)
        if any(
            self._runs[run_id].allocation
            != AllocationSemantics.UNCERTAIN_CONSERVED_POOL
            for run_id in relevant_runs
        ):
            raise GeneralSolverRequired(
                "mixed allocation semantics require general linear optimization"
            )

        source = ("special", "source")
        target_sink = ("special", "target")
        avoid_sink = ("special", "avoid")
        target_set = set(target_ids)

        consumed_by_batch: dict[str, Decimal] = defaultdict(Decimal)
        source_total = Decimal(0)
        for run in self._runs.values():
            for flow in run.consumed:
                batch_id = flow.holding.batch_id
                consumed_by_batch[batch_id] += flow.quantity.amount
                if batch_id == source_batch_id:
                    source_total += flow.quantity.amount

        remaining_by_output: dict[str, Decimal] = {}
        for output_id, quantity in self._output_quantity.items():
            remaining = quantity.amount - consumed_by_batch[output_id]
            if remaining < 0:
                raise ValueError(f"output is over-consumed: {output_id}")
            remaining_by_output[output_id] = remaining

        def network_edges(
            sink: tuple[str, str],
            collect_targets: bool,
        ) -> list[tuple[tuple[str, str], tuple[str, str], Decimal]]:
            edges: list[
                tuple[tuple[str, str], tuple[str, str], Decimal]
            ] = []

            for run in self._runs.values():
                run_node = ("run", run.run_id)
                for flow in run.consumed:
                    batch_id = flow.holding.batch_id
                    if batch_id == source_batch_id:
                        edges.append((source, run_node, flow.quantity.amount))
                    elif batch_id in self._output_quantity:
                        if batch_id not in target_set:
                            edges.append((
                                ("output", batch_id),
                                run_node,
                                flow.quantity.amount,
                            ))

                for flow in run.produced:
                    edges.append((
                        run_node,
                        ("output", flow.batch_id),
                        flow.quantity.amount,
                    ))
                for flow in run.losses:
                    edges.append((
                        run_node,
                        ("output", flow.loss_id),
                        flow.quantity.amount,
                    ))

            if collect_targets:
                for output_id in target_ids:
                    edges.append((
                        ("output", output_id),
                        sink,
                        self._output_quantity[output_id].amount,
                    ))
            else:
                for output_id, remaining in remaining_by_output.items():
                    if output_id not in target_set:
                        edges.append((("output", output_id), sink, remaining))

            return edges

        maximum = _maximum_flow(
            network_edges(target_sink, collect_targets=True),
            source,
            target_sink,
        )
        avoidable = _maximum_flow(
            network_edges(avoid_sink, collect_targets=False),
            source,
            avoid_sink,
        )
        minimum = source_total - avoidable
        if minimum < 0:
            raise AssertionError("maximum avoidable flow exceeded source flow")
        return ContributionBounds(minimum, maximum, unit)

    def _ancestor_run_ids(
        self,
        target_ids: Iterable[str],
        source_batch_id: str,
    ) -> set[str]:
        run_ids: set[str] = set()
        visiting: set[str] = set()

        def visit(output_id: str) -> None:
            if output_id == source_batch_id:
                return
            run_id = self._producer_by_output.get(output_id)
            if run_id is None or run_id in run_ids:
                return
            if run_id in visiting:
                raise ValueError("provenance graph contains a cycle")
            visiting.add(run_id)
            for flow in self._runs[run_id].consumed:
                visit(flow.holding.batch_id)
            visiting.remove(run_id)
            run_ids.add(run_id)

        for target_id in target_ids:
            visit(target_id)
        return run_ids
