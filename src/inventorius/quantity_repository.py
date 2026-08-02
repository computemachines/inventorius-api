"""Transactional writes for quantity-native operations and observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json
from typing import Any, Callable, Mapping
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from inventorius.inventory_repository import MissingBatch, MissingBin
from inventorius.inventory_serialization import reserve_inventory_resource
from inventorius.ledger import HoldingKey, IdempotencyConflict
from inventorius.quantity_codec import (
    OpeningEffect,
    QuantityClaim,
    effect_from_document,
    holding_document,
    observation_document,
    observation_from_document,
    opening_effect_document,
    output_state_id,
    quantity_stream_id,
    withdrawal_effect_document,
)
from inventorius.quantity_constraints import QuantityDomain
from inventorius.quantity_projection import quantity_json


class MissingQuantityHolding(ValueError):
    """The holding has no quantity-native opening fact."""


class QuantityManagedHolding(ValueError):
    """An exact-ledger command attempted to bypass a quantity-native stream."""


class QuantitySupersessionRejected(ValueError):
    """A supersession target is missing, unrelated, or already superseded."""


@dataclass(frozen=True)
class QuantityRepositoryResult:
    result: dict[str, Any]
    replayed: bool


def canonical_quantity_fingerprint(
    command: Mapping[str, Any],
    *,
    actor: dict[str, str] | None,
) -> str:
    normalized = dict(command)
    claim = normalized.get("claim")
    if isinstance(claim, QuantityClaim):
        from inventorius.quantity_codec import claim_document

        normalized["claim"] = claim_document(claim)
    encoded = json.dumps(
        {"actor": actor, "command": normalized},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def quantity_operation_document(
    *,
    operation_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    kind: str,
    result: dict[str, Any],
    now: datetime,
    actor: dict[str, str] | None,
    application_command: str,
    effect: dict[str, object],
) -> dict[str, Any]:
    """Build operation-v2 without pretending an interval is an exact leg."""

    document: dict[str, Any] = {
        "_id": operation_id,
        "idempotency_key": idempotency_key,
        "request_fingerprint": request_fingerprint,
        "kind": kind,
        "legs": [],
        "quantity_effect": effect,
        "created_at": now,
        "result": result,
        "fact_id": operation_id,
        "fact_type": "inventory.operation",
        "envelope_version": 1,
        "fact_schema": {"name": "inventory.operation", "version": 2},
        "recorded_at": now,
        "actor": actor,
        "command": {
            "command_id": operation_id,
            "name": application_command,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
        },
        "causation": {},
        "evidence": [],
    }
    return document


def opening_operation_and_head(
    *,
    operation_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    result: dict[str, Any],
    now: datetime,
    actor: dict[str, str] | None,
    holding: HoldingKey,
    domain: QuantityDomain,
    claim: QuantityClaim,
) -> tuple[dict[str, Any], dict[str, Any]]:
    state_id = output_state_id(operation_id, holding)
    effect = opening_effect_document(
        sequence=0,
        holding=holding,
        domain=domain,
        output_state=state_id,
        claim=claim,
    )
    operation = quantity_operation_document(
        operation_id=operation_id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        kind="receive",
        result=result,
        now=now,
        actor=actor,
        application_command="inventory.intake",
        effect=effect,
    )
    head = {
        "_id": quantity_stream_id(holding),
        "holding": holding_document(holding),
        "domain": domain.value,
        "current_state_id": state_id,
        "last_sequence": 0,
        "updated_at": now,
    }
    return operation, head


class QuantityRepository:
    """Append immutable evidence and state-changing operation-v2 facts."""

    def __init__(self, database):
        self.db = database
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.db.inventory_operations.create_index(
            [
                ("quantity_effect.stream_id", ASCENDING),
                ("quantity_effect.sequence", ASCENDING),
            ],
            unique=True,
            partialFilterExpression={
                "quantity_effect.stream_id": {"$type": "string"},
                "quantity_effect.sequence": {"$type": "number"},
            },
            name="quantity_operation_stream",
        )
        self.db.quantity_observations.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="quantity_observation_idempotency_key",
        )
        self.db.quantity_observations.create_index(
            [
                ("observation.stream_id", ASCENDING),
                ("observation.sequence", ASCENDING),
            ],
            name="quantity_observation_stream",
        )
        self.db.quantity_observations.create_index(
            [("observation.supersedes_fact_id", ASCENDING)],
            unique=True,
            partialFilterExpression={
                "observation.supersedes_fact_id": {"$type": "string"},
            },
            name="quantity_observation_single_supersession",
        )
        self.db.quantity_observations.create_index(
            [("recorded_at", DESCENDING), ("_id", DESCENDING)],
            name="quantity_observation_recent",
        )
        self.db.quantity_heads.create_index(
            [
                ("holding.batch_id", ASCENDING),
                ("holding.location_id", ASCENDING),
                ("holding.unit", ASCENDING),
                ("holding.packaging_configuration_id", ASCENDING),
            ],
            unique=True,
            name="quantity_head_holding_identity",
        )

    def _run_transaction(self, callback: Callable) -> Any:
        with self.db.client.start_session() as session:
            return session.with_transaction(
                callback,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )

    @staticmethod
    def _now() -> datetime:
        now = datetime.now(timezone.utc)
        return now.replace(microsecond=(now.microsecond // 1000) * 1000)

    def _reserve_holding(self, holding: HoldingKey, session) -> None:
        if reserve_inventory_resource(
            self.db.batch, holding.batch_id, session
        ) is None:
            raise MissingBatch(holding.batch_id)
        if reserve_inventory_resource(
            self.db.bin, holding.location_id, session
        ) is None:
            raise MissingBin(holding.location_id)

    def _head(self, holding: HoldingKey, session) -> dict[str, Any]:
        stream_id = quantity_stream_id(holding)
        head = self.db.quantity_heads.find_one({"_id": stream_id}, session=session)
        if head is None:
            raise MissingQuantityHolding(stream_id)
        if head.get("holding") != holding_document(holding):
            raise RuntimeError("quantity head identity is corrupt")
        return head

    def _observation_existing(
        self,
        idempotency_key: str,
        fingerprint: str,
        session,
    ) -> QuantityRepositoryResult | None:
        document = self.db.quantity_observations.find_one(
            {"idempotency_key": idempotency_key}, session=session
        )
        if document is None:
            return None
        if document.get("request_fingerprint") != fingerprint:
            raise IdempotencyConflict(
                "idempotency key belongs to another quantity observation"
            )
        return QuantityRepositoryResult(
            self._serialize_observation(document), replayed=True
        )

    @staticmethod
    def _serialize_observation(document: Mapping[str, Any]) -> dict[str, Any]:
        evidence = observation_from_document(document.get("observation"))
        recorded_at = document.get("recorded_at")
        if isinstance(recorded_at, datetime):
            recorded_at = recorded_at.replace(
                tzinfo=recorded_at.tzinfo or timezone.utc
            ).isoformat()
        return {
            "observation_id": document.get("_id"),
            "stream_id": evidence.stream_id,
            "sequence": evidence.sequence,
            "holding": holding_document(evidence.holding),
            "state_id": evidence.state_id,
            "domain": evidence.domain.value,
            "basis": evidence.claim.basis.value,
            "lower": quantity_json(evidence.claim.lower),
            "preferred": quantity_json(evidence.claim.preferred),
            "upper": quantity_json(evidence.claim.upper),
            "capacity": quantity_json(evidence.claim.capacity),
            "supersedes_fact_id": evidence.supersedes_fact_id,
            "recorded_at": recorded_at,
        }

    def _validate_supersession(
        self,
        target_id: str,
        stream_id: str,
        session,
    ) -> None:
        target = self.db.quantity_observations.find_one(
            {"_id": target_id}, session=session
        )
        if target is not None:
            target_evidence = observation_from_document(target.get("observation"))
            target_stream_id = target_evidence.stream_id
        else:
            target = self.db.inventory_operations.find_one(
                {"_id": target_id, "quantity_effect": {"$exists": True}},
                session=session,
            )
            if target is None:
                raise QuantitySupersessionRejected("superseded fact does not exist")
            effect = effect_from_document(target.get("quantity_effect"))
            if not isinstance(effect, OpeningEffect):
                raise QuantitySupersessionRejected(
                    "only quantity claims can be superseded"
                )
            target_stream_id = effect.stream_id
        if target_stream_id != stream_id:
            raise QuantitySupersessionRejected(
                "superseded fact belongs to another holding"
            )
        if self.db.quantity_observations.find_one(
            {"observation.supersedes_fact_id": target_id},
            {"_id": 1},
            session=session,
        ) is not None:
            raise QuantitySupersessionRejected("fact is already superseded")

    def record_observation(
        self,
        command: dict[str, Any],
        *,
        idempotency_key: str,
        actor: dict[str, str] | None,
    ) -> QuantityRepositoryResult:
        claim = command["claim"]
        if not isinstance(claim, QuantityClaim):
            raise ValueError("command claim must be a QuantityClaim")
        holding = HoldingKey(
            command["batch_id"],
            command["location_id"],
            command["unit"],
            command.get("packaging_configuration_id"),
        )
        fingerprint = canonical_quantity_fingerprint(command, actor=actor)

        def write(session):
            existing = self._observation_existing(
                idempotency_key, fingerprint, session
            )
            if existing is not None:
                return existing
            self._reserve_holding(holding, session)
            head = self._head(holding, session)
            try:
                domain = QuantityDomain(head["domain"])
            except (KeyError, ValueError) as error:
                raise RuntimeError("quantity head domain is corrupt") from error
            supplied_domain = command["domain"]
            if supplied_domain != domain:
                raise ValueError("observation domain does not match quantity holding")
            supersedes = command.get("supersedes_fact_id")
            if supersedes is not None:
                self._validate_supersession(supersedes, head["_id"], session)

            observation_id = f"QOB{uuid4().hex}"
            sequence = head["last_sequence"] + 1
            now = self._now()
            payload = observation_document(
                sequence=sequence,
                holding=holding,
                domain=domain,
                state_id=head["current_state_id"],
                claim=claim,
                supersedes_fact_id=supersedes,
            )
            document = {
                "_id": observation_id,
                "fact_id": observation_id,
                "fact_type": "inventory.quantity-observation",
                "envelope_version": 1,
                "fact_schema": {
                    "name": "inventory.quantity-observation",
                    "version": 1,
                },
                "recorded_at": now,
                "actor": actor,
                "command": {
                    "command_id": observation_id,
                    "name": "inventory.quantity-observation",
                    "idempotency_key": idempotency_key,
                    "request_fingerprint": fingerprint,
                },
                "causation": (
                    {}
                    if supersedes is None
                    else {"supersedes": supersedes}
                ),
                "evidence": [],
                "idempotency_key": idempotency_key,
                "request_fingerprint": fingerprint,
                "observation": payload,
            }
            self.db.quantity_observations.insert_one(document, session=session)
            updated = self.db.quantity_heads.update_one(
                {"_id": head["_id"], "last_sequence": head["last_sequence"]},
                {"$set": {"last_sequence": sequence, "updated_at": now}},
                session=session,
            )
            if updated.modified_count != 1:
                raise RuntimeError("quantity head changed during observation")
            return QuantityRepositoryResult(
                self._serialize_observation(document), replayed=False
            )

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            existing = self.db.quantity_observations.find_one(
                {"idempotency_key": idempotency_key}
            )
            if existing is None:
                raise error
            if existing.get("request_fingerprint") != fingerprint:
                raise IdempotencyConflict(
                    "idempotency key belongs to another quantity observation"
                ) from error
            return QuantityRepositoryResult(
                self._serialize_observation(existing), replayed=True
            )

    def record_withdrawal(
        self,
        command: dict[str, Any],
        *,
        idempotency_key: str,
        actor: dict[str, str] | None,
    ) -> QuantityRepositoryResult:
        holding = HoldingKey(
            command["batch_id"],
            command["location_id"],
            command["unit"],
            command.get("packaging_configuration_id"),
        )
        amount = Fraction(command["amount"])
        if amount <= 0:
            raise ValueError("withdrawal amount must be positive")
        semantic_command = dict(command, amount=str(amount))
        fingerprint = canonical_quantity_fingerprint(
            semantic_command, actor=actor
        )

        def write(session):
            existing = self.db.inventory_operations.find_one(
                {"idempotency_key": idempotency_key}, session=session
            )
            if existing is not None:
                if existing.get("request_fingerprint") != fingerprint:
                    raise IdempotencyConflict(
                        "idempotency key belongs to another inventory operation"
                    )
                return QuantityRepositoryResult(existing["result"], replayed=True)
            self._reserve_holding(holding, session)
            head = self._head(holding, session)
            domain = QuantityDomain(head["domain"])
            if command["domain"] != domain:
                raise ValueError("withdrawal domain does not match quantity holding")
            if domain == QuantityDomain.DISCRETE and amount.denominator != 1:
                raise ValueError("discrete withdrawal must be a whole amount")

            operation_id = f"OP{uuid4().hex}"
            sequence = head["last_sequence"] + 1
            state_id = output_state_id(operation_id, holding)
            now = self._now()
            effect = withdrawal_effect_document(
                sequence=sequence,
                holding=holding,
                domain=domain,
                predecessor_state=head["current_state_id"],
                output_state=state_id,
                amount=amount,
            )
            result = {
                "operation_id": operation_id,
                "kind": "release",
                "batch_id": holding.batch_id,
                "location_id": holding.location_id,
                "amount": quantity_json(amount),
                "unit": holding.unit,
                "packaging_configuration_id": (
                    holding.packaging_configuration_id
                ),
                "quantity_native": True,
            }
            document = quantity_operation_document(
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                kind="release",
                result=result,
                now=now,
                actor=actor,
                application_command="inventory.quantity-withdrawal",
                effect=effect,
            )
            self.db.inventory_operations.insert_one(document, session=session)
            updated = self.db.quantity_heads.update_one(
                {"_id": head["_id"], "last_sequence": head["last_sequence"]},
                {"$set": {
                    "last_sequence": sequence,
                    "current_state_id": state_id,
                    "updated_at": now,
                }},
                session=session,
            )
            if updated.modified_count != 1:
                raise RuntimeError("quantity head changed during withdrawal")
            return QuantityRepositoryResult(result, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            existing = self.db.inventory_operations.find_one(
                {"idempotency_key": idempotency_key}
            )
            if existing is None:
                raise error
            if existing.get("request_fingerprint") != fingerprint:
                raise IdempotencyConflict(
                    "idempotency key belongs to another inventory operation"
                ) from error
            return QuantityRepositoryResult(existing["result"], replayed=True)
