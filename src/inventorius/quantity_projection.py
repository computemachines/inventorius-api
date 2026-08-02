"""Rebuildable physical-quantity views over semantic source facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any, Iterable, Mapping

from bson.decimal128 import Decimal128
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from inventorius.ledger import HoldingKey
from inventorius.quantity_codec import (
    OpeningEffect,
    QuantityClaim,
    QuantityEvidence,
    WithdrawalEffect,
    effect_from_document,
    holding_document,
    observation_from_document,
    quantity_stream_id,
)
from inventorius.quantity_constraints import (
    InfeasibleQuantityFacts,
    ObservationBasis,
    QuantityHistory,
    QuantityObservation,
    QuantityQueryIndeterminate,
)


class QuantityProjectionError(ValueError):
    """Stored quantity facts cannot be replayed without inventing history."""


@dataclass(frozen=True)
class StoredQuantityEvent:
    fact_id: str
    sequence: int
    recorded_at: datetime | None
    effect: OpeningEffect | WithdrawalEffect | QuantityEvidence
    source: str


@dataclass(frozen=True)
class CompiledQuantityStream:
    stream_id: str
    holding: HoldingKey
    domain: str
    current_state_id: str
    last_sequence: int
    view: dict[str, Any]
    history: tuple[dict[str, Any], ...]


def quantity_json(value: Fraction | None) -> int | str | None:
    if value is None:
        return None
    if value.denominator == 1:
        integer = value.numerator
        if abs(integer) <= 9_007_199_254_740_991:
            return integer
        return str(integer)
    denominator = value.denominator
    reduced = denominator
    while reduced % 2 == 0:
        reduced //= 2
    while reduced % 5 == 0:
        reduced //= 5
    if reduced == 1:
        # Finite decimal; Fraction -> Decimal via long division without a
        # context that could round an arbitrary rational.
        scale = 0
        power = 1
        while power % denominator:
            power *= 10
            scale += 1
        scaled = value.numerator * (power // denominator)
        sign = "-" if scaled < 0 else ""
        digits = str(abs(scaled)).zfill(scale + 1)
        rendered = f"{sign}{digits[:-scale]}.{digits[-scale:]}" if scale else f"{sign}{digits}"
        return rendered.rstrip("0").rstrip(".")
    return f"{value.numerator}/{value.denominator}"


def _datetime(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise QuantityProjectionError(f"{field} must be a datetime")
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


def _fact_id(document: Mapping[str, Any], field: str) -> str:
    fact_id = document.get("fact_id", document.get("_id"))
    if not isinstance(fact_id, str) or not fact_id:
        raise QuantityProjectionError(f"{field} has no fact identity")
    if document.get("_id") != fact_id:
        raise QuantityProjectionError(f"{field} fact identity is inconsistent")
    return fact_id


def _schema(document: Mapping[str, Any], *, name: str, version: int, field: str) -> None:
    if document.get("fact_type") != name:
        raise QuantityProjectionError(f"{field} has an unsupported fact type")
    if document.get("envelope_version") != 1:
        raise QuantityProjectionError(f"{field} has an unsupported envelope version")
    schema = document.get("fact_schema")
    if not isinstance(schema, Mapping) or set(schema) != {"name", "version"}:
        raise QuantityProjectionError(f"{field} has a malformed fact schema")
    if schema.get("name") != name or schema.get("version") != version:
        raise QuantityProjectionError(f"{field} has an unsupported fact schema")


def operation_event(document: Mapping[str, Any]) -> StoredQuantityEvent:
    fact_id = _fact_id(document, "quantity operation")
    _schema(
        document,
        name="inventory.operation",
        version=2,
        field=f"operation {fact_id}",
    )
    try:
        effect = effect_from_document(document.get("quantity_effect"))
    except ValueError as error:
        raise QuantityProjectionError(f"operation {fact_id}: {error}") from error
    return StoredQuantityEvent(
        fact_id,
        effect.sequence,
        _datetime(document.get("recorded_at", document.get("created_at")), f"operation {fact_id}.recorded_at"),
        effect,
        "operation",
    )


def observation_event(document: Mapping[str, Any]) -> StoredQuantityEvent:
    fact_id = _fact_id(document, "quantity observation")
    _schema(
        document,
        name="inventory.quantity-observation",
        version=1,
        field=f"observation {fact_id}",
    )
    try:
        evidence = observation_from_document(document.get("observation"))
    except ValueError as error:
        raise QuantityProjectionError(f"observation {fact_id}: {error}") from error
    return StoredQuantityEvent(
        fact_id,
        evidence.sequence,
        _datetime(document.get("recorded_at"), f"observation {fact_id}.recorded_at"),
        evidence,
        "observation",
    )


def _claim_summary(claim: QuantityClaim | None) -> dict[str, Any] | None:
    if claim is None:
        return None
    return {
        "basis": claim.basis.value,
        "lower": quantity_json(claim.lower),
        "preferred": quantity_json(claim.preferred),
        "upper": quantity_json(claim.upper),
        "capacity": quantity_json(claim.capacity),
    }


def compile_quantity_stream(
    operation_documents: Iterable[Mapping[str, Any]],
    observation_documents: Iterable[Mapping[str, Any]],
) -> CompiledQuantityStream:
    """Strictly replay one stream, independent of Mongo cursor order."""

    events = [operation_event(document) for document in operation_documents]
    events.extend(
        observation_event(document) for document in observation_documents
    )
    if not events:
        raise QuantityProjectionError("a quantity stream needs at least one event")
    stream_ids = {event.effect.stream_id for event in events}
    if len(stream_ids) != 1:
        raise QuantityProjectionError("events from different quantity streams were mixed")
    events.sort(key=lambda event: event.sequence)
    sequences = [event.sequence for event in events]
    if sequences != list(range(len(events))):
        raise QuantityProjectionError(
            "quantity stream sequences must be unique and contiguous from zero"
        )
    first = events[0]
    if not isinstance(first.effect, OpeningEffect):
        raise QuantityProjectionError("quantity stream must start with an opening effect")
    holding = first.effect.holding
    domain = first.effect.domain
    if any(
        event.effect.holding != holding or event.effect.domain != domain
        for event in events
    ):
        raise QuantityProjectionError("quantity stream changes holding identity or domain")

    facts_by_id = {event.fact_id: event for event in events}
    if len(facts_by_id) != len(events):
        raise QuantityProjectionError("quantity stream has duplicate fact identities")
    superseded: set[str] = set()
    successor_by_target: dict[str, str] = {}
    for event in events:
        effect = event.effect
        if not isinstance(effect, QuantityEvidence):
            continue
        target = effect.supersedes_fact_id
        if target is None:
            continue
        target_event = facts_by_id.get(target)
        if target_event is None or target_event.sequence >= event.sequence:
            raise QuantityProjectionError(
                f"observation {event.fact_id} has a dangling or forward supersession"
            )
        if isinstance(target_event.effect, WithdrawalEffect):
            raise QuantityProjectionError("withdrawal effects cannot be superseded as evidence")
        if target in successor_by_target:
            raise QuantityProjectionError("quantity evidence has multiple superseding facts")
        successor_by_target[target] = event.fact_id
        superseded.add(target)

    history = QuantityHistory()
    opening_claim = (
        first.effect.claim
        if first.fact_id not in superseded
        else QuantityClaim(
            basis=ObservationBasis.CALCULATED,
            lower=0,
        )
    )
    history.open_holding(
        holding,
        domain,
        opening_claim.as_observation(first.fact_id),
    )
    current_state_id = first.effect.output_state_id
    active_current_claim: tuple[StoredQuantityEvent, QuantityClaim] | None = (
        None
        if first.fact_id in superseded
        else (first, first.effect.claim)
    )

    for event in events[1:]:
        effect = event.effect
        if isinstance(effect, OpeningEffect):
            raise QuantityProjectionError("quantity stream has more than one opening")
        if isinstance(effect, WithdrawalEffect):
            if effect.predecessor_state_id != current_state_id:
                raise QuantityProjectionError(
                    f"operation {event.fact_id} does not consume the current state"
                )
            history.record_exact_withdrawal(
                event.fact_id,
                holding,
                effect.amount,
            )
            current_state_id = effect.output_state_id
            active_current_claim = None
            continue
        if effect.state_id != current_state_id:
            raise QuantityProjectionError(
                f"observation {event.fact_id} does not target the current state"
            )
        if event.fact_id not in superseded:
            history.observe_current(
                holding,
                effect.claim.as_observation(event.fact_id),
            )
            active_current_claim = (event, effect.claim)

    status = "feasible"
    conflict_fact_ids: list[str] = []
    minimum = maximum = None
    try:
        bounds = history.current_physical_bounds(holding)
        minimum, maximum = bounds.minimum, bounds.maximum
    except InfeasibleQuantityFacts as error:
        status = "conflict"
        conflict_fact_ids = sorted({
            fact_id.rsplit(":", 1)[0] for fact_id in error.fact_ids
        })
    except QuantityQueryIndeterminate:
        status = "indeterminate"

    current_claim = active_current_claim[1] if active_current_claim else None
    view = {
        "status": status,
        "minimum": quantity_json(minimum),
        "maximum": quantity_json(maximum),
        "preferred": (
            None
            if current_claim is None
            else quantity_json(current_claim.preferred)
        ),
        "capacity": (
            None
            if current_claim is None
            else quantity_json(current_claim.capacity)
        ),
        "unit": holding.unit,
        "domain": domain.value,
        "conflict_fact_ids": conflict_fact_ids,
    }
    serialized_history = []
    for event in reversed(events):
        effect = event.effect
        claim = (
            effect.claim
            if isinstance(effect, (OpeningEffect, QuantityEvidence))
            else None
        )
        serialized_history.append({
            "fact_id": event.fact_id,
            "sequence": event.sequence,
            "kind": (
                "observation"
                if isinstance(effect, QuantityEvidence)
                else effect.__class__.__name__.removesuffix("Effect").lower()
            ),
            "recorded_at": (
                None
                if event.recorded_at is None
                else event.recorded_at.isoformat()
            ),
            "active": event.fact_id not in superseded,
            "superseded_by_fact_id": successor_by_target.get(event.fact_id),
            "claim": _claim_summary(claim),
            "amount": (
                quantity_json(effect.amount)
                if isinstance(effect, WithdrawalEffect)
                else None
            ),
        })
    return CompiledQuantityStream(
        first.effect.stream_id,
        holding,
        domain.value,
        current_state_id,
        events[-1].sequence,
        view,
        tuple(serialized_history),
    )


def _book_view(database, holding: HoldingKey) -> dict[str, Any]:
    document = database.inventory_holdings.find_one(holding_document(holding))
    if document is None:
        return {"status": "absent", "quantity": None, "unit": holding.unit}
    raw = document.get("quantity")
    value = raw.to_decimal() if isinstance(raw, Decimal128) else raw
    return {
        "status": "exact",
        "quantity": int(value) if value == int(value) else str(value),
        "unit": holding.unit,
    }


def read_quantity_stream(database, stream_id: str) -> CompiledQuantityStream:
    operations = list(database.inventory_operations.find({
        "quantity_effect.stream_id": stream_id,
    }))
    observations = list(database.quantity_observations.find({
        "observation.stream_id": stream_id,
    }))
    return compile_quantity_stream(operations, observations)


def quantity_holding_resource(database, stream_id: str) -> dict[str, Any]:
    compiled = read_quantity_stream(database, stream_id)
    return {
        "stream_id": compiled.stream_id,
        "holding": holding_document(compiled.holding),
        "current_state_id": compiled.current_state_id,
        "last_sequence": compiled.last_sequence,
        "accepted_book": _book_view(database, compiled.holding),
        "feasible_physical": compiled.view,
        "history": list(compiled.history),
    }


def quantity_holding_resources(
    database,
    *,
    batch_id: str | None = None,
    location_id: str | None = None,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if batch_id is not None:
        query["holding.batch_id"] = batch_id
    if location_id is not None:
        query["holding.location_id"] = location_id
    heads = list(database.quantity_heads.find(query, {"_id": 1}).sort("_id", 1))
    return [quantity_holding_resource(database, head["_id"]) for head in heads]


def rebuilt_quantity_heads(database, *, replace: bool = False) -> dict[str, Any]:
    """Derive every routing head from source facts and optionally replace them."""

    stream_ids = {
        document["quantity_effect"]["stream_id"]
        for document in database.inventory_operations.find(
            {"quantity_effect": {"$exists": True}},
            {"quantity_effect.stream_id": 1},
        )
        if isinstance(document.get("quantity_effect"), Mapping)
        and isinstance(document["quantity_effect"].get("stream_id"), str)
    }
    stream_ids.update({
        document["observation"]["stream_id"]
        for document in database.quantity_observations.find(
            {}, {"observation.stream_id": 1}
        )
        if isinstance(document.get("observation"), Mapping)
        and isinstance(document["observation"].get("stream_id"), str)
    })
    expected = []
    for stream_id in sorted(stream_ids):
        compiled = read_quantity_stream(database, stream_id)
        expected.append({
            "_id": stream_id,
            "holding": holding_document(compiled.holding),
            "domain": compiled.domain,
            "current_state_id": compiled.current_state_id,
            "last_sequence": compiled.last_sequence,
        })

    actual = list(database.quantity_heads.find({}, {"updated_at": 0}).sort("_id", 1))
    consistent = actual == expected
    if replace:
        def write(session):
            database.quantity_heads.delete_many({}, session=session)
            if expected:
                database.quantity_heads.insert_many(expected, session=session)

        with database.client.start_session() as session:
            session.with_transaction(
                write,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )
        consistent = True
    return {
        "is_consistent": consistent,
        "stream_count": len(expected),
        "expected": expected,
        "actual": actual,
    }
