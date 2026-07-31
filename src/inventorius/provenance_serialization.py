"""Lossless, versioned serialization for provenance constraint sets.

The document retains observations and their correlations rather than derived
``ContributionBounds``.  Rehydration therefore reconstructs the queryable
``ProvenanceNetwork`` and lets its solver derive bounds from the original
constraints again.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from inventorius.provenance import (
    AllocationSemantics,
    AssemblyRun,
    ComponentUse,
    ConsumedHolding,
    HoldingReference,
    MaterialLoss,
    ProducedHolding,
    ProvenanceNetwork,
    Quantity,
    TransformationRun,
)


CODEC_NAME = "inventorius.provenance-constraint-set"
CODEC_VERSION = 1

Document = dict[str, object]


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


def _positive_finite_amount(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field} must be a decimal string") from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return amount


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise ValueError(f"{field} must be an array")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unexpected {unexpected}")
        raise ValueError(f"{field} has invalid fields: {', '.join(details)}")


def _validate_quantity(quantity: Quantity, field: str) -> None:
    if not isinstance(quantity, Quantity):
        raise ValueError(f"{field} must be a Quantity")
    if not isinstance(quantity.amount, Decimal):
        raise ValueError(f"{field}.amount must be a Decimal")
    if not quantity.amount.is_finite() or quantity.amount <= 0:
        raise ValueError(f"{field}.amount must be finite and positive")
    _nonblank(quantity.unit, f"{field}.unit")


def _validate_holding(holding: HoldingReference, field: str) -> None:
    if not isinstance(holding, HoldingReference):
        raise ValueError(f"{field} must be a HoldingReference")
    _nonblank(holding.batch_id, f"{field}.batch_id")
    _nonblank(holding.location_id, f"{field}.location_id")


def _validate_constraint_set(
    transformations: tuple[TransformationRun, ...],
    assemblies: tuple[AssemblyRun, ...],
) -> None:
    run_ids: set[str] = set()
    output_ids: set[str] = set()

    def register_run(run_id: object) -> None:
        stable_id = _nonblank(run_id, "run_id")
        if stable_id in run_ids:
            raise ValueError(f"duplicate run: {stable_id}")
        run_ids.add(stable_id)

    def register_output(output_id: object) -> None:
        stable_id = _nonblank(output_id, "output_id")
        if stable_id in output_ids:
            raise ValueError(f"output already has a producer: {stable_id}")
        output_ids.add(stable_id)

    for run in transformations:
        if not isinstance(run, TransformationRun):
            raise ValueError("transformations must contain TransformationRun")
        register_run(run.run_id)
        if not isinstance(run.allocation, AllocationSemantics):
            raise ValueError("transformation allocation must be supported")
        for index, flow in enumerate(run.consumed):
            if not isinstance(flow, ConsumedHolding):
                raise ValueError("consumed flows must be ConsumedHolding")
            _validate_holding(flow.holding, f"consumed[{index}].holding")
            _validate_quantity(flow.quantity, f"consumed[{index}].quantity")
        for index, flow in enumerate(run.produced):
            if not isinstance(flow, ProducedHolding):
                raise ValueError("produced flows must be ProducedHolding")
            _nonblank(flow.batch_id, f"produced[{index}].batch_id")
            _nonblank(flow.location_id, f"produced[{index}].location_id")
            _validate_quantity(flow.quantity, f"produced[{index}].quantity")
            register_output(flow.batch_id)
        for index, flow in enumerate(run.losses):
            if not isinstance(flow, MaterialLoss):
                raise ValueError("loss flows must be MaterialLoss")
            _nonblank(flow.loss_id, f"losses[{index}].loss_id")
            _nonblank(flow.reason, f"losses[{index}].reason")
            _validate_quantity(flow.quantity, f"losses[{index}].quantity")
            register_output(flow.loss_id)

    for run in assemblies:
        if not isinstance(run, AssemblyRun):
            raise ValueError("assemblies must contain AssemblyRun")
        register_run(run.run_id)
        for index, component in enumerate(run.components):
            if not isinstance(component, ComponentUse):
                raise ValueError("assembly components must be ComponentUse")
            _validate_holding(
                component.holding,
                f"components[{index}].holding",
            )
            _validate_quantity(
                component.quantity,
                f"components[{index}].quantity",
            )
            _nonblank(component.role, f"components[{index}].role")
        _nonblank(run.produced.batch_id, "assembly.produced.batch_id")
        _nonblank(run.produced.location_id, "assembly.produced.location_id")
        _validate_quantity(run.produced.quantity, "assembly.produced.quantity")
        register_output(run.produced.batch_id)

    # Reuse the domain kernel for conservation, compatible-unit, structural,
    # and producer invariants rather than duplicating them in the codec.
    network = ProvenanceNetwork()
    for run in transformations:
        network.add_run(run)
    for run in assemblies:
        network.add_assembly(run)


@dataclass(frozen=True)
class ProvenanceConstraintSet:
    """An immutable collection of correlated provenance observations."""

    transformations: tuple[TransformationRun, ...] = ()
    assemblies: tuple[AssemblyRun, ...] = ()

    def __init__(
        self,
        transformations: Sequence[TransformationRun] = (),
        assemblies: Sequence[AssemblyRun] = (),
    ):
        frozen_transformations = tuple(transformations)
        frozen_assemblies = tuple(assemblies)
        _validate_constraint_set(frozen_transformations, frozen_assemblies)
        object.__setattr__(self, "transformations", frozen_transformations)
        object.__setattr__(self, "assemblies", frozen_assemblies)

    def to_network(self) -> ProvenanceNetwork:
        """Rehydrate a queryable network from the retained constraints."""

        network = ProvenanceNetwork()
        for run in self.transformations:
            network.add_run(run)
        for run in self.assemblies:
            network.add_assembly(run)
        return network

    def to_document(self) -> Document:
        """Return a JSON-compatible, lossless versioned document."""

        return {
            "codec": {"name": CODEC_NAME, "version": CODEC_VERSION},
            "transformation_runs": [
                _transformation_to_document(run)
                for run in self.transformations
            ],
            "assembly_runs": [
                _assembly_to_document(run) for run in self.assemblies
            ],
        }

    @classmethod
    def from_document(cls, document: object) -> ProvenanceConstraintSet:
        """Decode one frozen codec version, rejecting unknown semantics."""

        root = _mapping(document, "document")
        _exact_keys(
            root,
            {"codec", "transformation_runs", "assembly_runs"},
            "document",
        )
        codec = _mapping(root["codec"], "codec")
        _exact_keys(codec, {"name", "version"}, "codec")
        if codec["name"] != CODEC_NAME:
            raise ValueError(f"unsupported provenance codec: {codec['name']!r}")
        if type(codec["version"]) is not int or codec["version"] != CODEC_VERSION:
            raise ValueError(
                f"unsupported provenance codec version: {codec['version']!r}"
            )

        transformations = tuple(
            _transformation_from_document(item, index)
            for index, item in enumerate(
                _sequence(root["transformation_runs"], "transformation_runs")
            )
        )
        assemblies = tuple(
            _assembly_from_document(item, index)
            for index, item in enumerate(
                _sequence(root["assembly_runs"], "assembly_runs")
            )
        )
        return cls(transformations, assemblies)


def _quantity_to_document(quantity: Quantity) -> Document:
    return {"amount": str(quantity.amount), "unit": quantity.unit}


def _quantity_from_document(value: object, field: str) -> Quantity:
    document = _mapping(value, field)
    _exact_keys(document, {"amount", "unit"}, field)
    amount = _positive_finite_amount(document["amount"], f"{field}.amount")
    unit = _nonblank(document["unit"], f"{field}.unit")
    return Quantity(amount, unit)


def _holding_to_document(holding: HoldingReference) -> Document:
    return {
        "batch_id": holding.batch_id,
        "location_id": holding.location_id,
    }


def _holding_from_document(value: object, field: str) -> HoldingReference:
    document = _mapping(value, field)
    _exact_keys(document, {"batch_id", "location_id"}, field)
    return HoldingReference(
        _nonblank(document["batch_id"], f"{field}.batch_id"),
        _nonblank(document["location_id"], f"{field}.location_id"),
    )


def _consumed_to_document(flow: ConsumedHolding) -> Document:
    return {
        "holding": _holding_to_document(flow.holding),
        "quantity": _quantity_to_document(flow.quantity),
    }


def _consumed_from_document(value: object, field: str) -> ConsumedHolding:
    document = _mapping(value, field)
    _exact_keys(document, {"holding", "quantity"}, field)
    return ConsumedHolding(
        _holding_from_document(document["holding"], f"{field}.holding"),
        _quantity_from_document(document["quantity"], f"{field}.quantity"),
    )


def _produced_to_document(flow: ProducedHolding) -> Document:
    return {
        "holding": _holding_to_document(
            HoldingReference(flow.batch_id, flow.location_id)
        ),
        "quantity": _quantity_to_document(flow.quantity),
    }


def _produced_from_document(value: object, field: str) -> ProducedHolding:
    document = _mapping(value, field)
    _exact_keys(document, {"holding", "quantity"}, field)
    holding = _holding_from_document(document["holding"], f"{field}.holding")
    return ProducedHolding(
        holding.batch_id,
        holding.location_id,
        _quantity_from_document(document["quantity"], f"{field}.quantity"),
    )


def _loss_to_document(loss: MaterialLoss) -> Document:
    return {
        "loss_id": loss.loss_id,
        "reason": loss.reason,
        "quantity": _quantity_to_document(loss.quantity),
    }


def _loss_from_document(value: object, field: str) -> MaterialLoss:
    document = _mapping(value, field)
    _exact_keys(document, {"loss_id", "reason", "quantity"}, field)
    return MaterialLoss(
        _nonblank(document["loss_id"], f"{field}.loss_id"),
        _nonblank(document["reason"], f"{field}.reason"),
        _quantity_from_document(document["quantity"], f"{field}.quantity"),
    )


def _transformation_to_document(run: TransformationRun) -> Document:
    return {
        "run_id": run.run_id,
        "allocation": run.allocation.value,
        "consumed": [_consumed_to_document(flow) for flow in run.consumed],
        "produced": [_produced_to_document(flow) for flow in run.produced],
        "losses": [_loss_to_document(flow) for flow in run.losses],
    }


def _transformation_from_document(
    value: object,
    index: int,
) -> TransformationRun:
    field = f"transformation_runs[{index}]"
    document = _mapping(value, field)
    _exact_keys(
        document,
        {"run_id", "allocation", "consumed", "produced", "losses"},
        field,
    )
    allocation_value = _nonblank(
        document["allocation"],
        f"{field}.allocation",
    )
    try:
        allocation = AllocationSemantics(allocation_value)
    except ValueError as error:
        raise ValueError(
            f"{field}.allocation has unsupported semantics: "
            f"{allocation_value!r}"
        ) from error
    return TransformationRun(
        run_id=_nonblank(document["run_id"], f"{field}.run_id"),
        allocation=allocation,
        consumed=tuple(
            _consumed_from_document(item, f"{field}.consumed[{flow_index}]")
            for flow_index, item in enumerate(
                _sequence(document["consumed"], f"{field}.consumed")
            )
        ),
        produced=tuple(
            _produced_from_document(item, f"{field}.produced[{flow_index}]")
            for flow_index, item in enumerate(
                _sequence(document["produced"], f"{field}.produced")
            )
        ),
        losses=tuple(
            _loss_from_document(item, f"{field}.losses[{flow_index}]")
            for flow_index, item in enumerate(
                _sequence(document["losses"], f"{field}.losses")
            )
        ),
    )


def _component_to_document(component: ComponentUse) -> Document:
    return {
        "holding": _holding_to_document(component.holding),
        "quantity": _quantity_to_document(component.quantity),
        "role": component.role,
    }


def _component_from_document(value: object, field: str) -> ComponentUse:
    document = _mapping(value, field)
    _exact_keys(document, {"holding", "quantity", "role"}, field)
    return ComponentUse(
        _holding_from_document(document["holding"], f"{field}.holding"),
        _quantity_from_document(document["quantity"], f"{field}.quantity"),
        _nonblank(document["role"], f"{field}.role"),
    )


def _assembly_to_document(run: AssemblyRun) -> Document:
    return {
        "run_id": run.run_id,
        "components": [
            _component_to_document(component) for component in run.components
        ],
        "produced": _produced_to_document(run.produced),
    }


def _assembly_from_document(value: object, index: int) -> AssemblyRun:
    field = f"assembly_runs[{index}]"
    document = _mapping(value, field)
    _exact_keys(document, {"run_id", "components", "produced"}, field)
    return AssemblyRun(
        run_id=_nonblank(document["run_id"], f"{field}.run_id"),
        components=tuple(
            _component_from_document(
                item,
                f"{field}.components[{component_index}]",
            )
            for component_index, item in enumerate(
                _sequence(document["components"], f"{field}.components")
            )
        ),
        produced=_produced_from_document(
            document["produced"],
            f"{field}.produced",
        ),
    )


def provenance_network_from_document(document: object) -> ProvenanceNetwork:
    """Decode and rehydrate a provenance document in one step."""

    return ProvenanceConstraintSet.from_document(document).to_network()
