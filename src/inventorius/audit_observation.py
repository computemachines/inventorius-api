"""Durable, append-only physical-count observations.

An audit observation records what a person reviewed against one exact holding
snapshot. It is evidence, not an inventory command: this module never updates
``inventory_holdings``, appends an ``inventory_operation``, or promotes legacy
``bin.contents``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from typing import Any, Callable
from uuid import uuid4

from bson.decimal128 import Decimal128, create_decimal128_context
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from inventorius.audit_snapshot import read_audit_snapshot
from inventorius.inventory_repository import MissingBatch, MissingBin
from inventorius.inventory_serialization import reserve_inventory_resource
from inventorius.ledger import IdempotencyConflict


MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991
DECIMAL128_CONTEXT = create_decimal128_context()


class AuditSnapshotStale(ValueError):
    """The submitted token no longer names the location's current snapshot."""

    def __init__(self, current_snapshot_token: str):
        self.current_snapshot_token = current_snapshot_token
        super().__init__("the audit snapshot changed before it was recorded")


class AuditSnapshotBlocked(ValueError):
    """The current snapshot has data the audit boundary cannot interpret."""

    def __init__(self, blockers: list[dict[str, Any]]):
        self.blockers = blockers
        super().__init__("the current audit snapshot has blockers")


class AuditCountsRejected(ValueError):
    """Reviewed counts do not exactly cover the current supported snapshot."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class AuditObservationResult:
    """One public observation plus whether it was an idempotent replay."""

    observation: dict[str, Any]
    replayed: bool


def _decimal(value: Decimal128 | Decimal | int | str | None) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _decimal128(value: Decimal | int | str) -> Decimal128:
    return Decimal128(str(_decimal(value)))


def _subtract(left: Decimal, right: Decimal) -> Decimal:
    """Keep Decimal128 whole-item differences exact beyond 28 digits."""
    with localcontext(DECIMAL128_CONTEXT):
        return left - right


def _quantity_json(value: Decimal128 | Decimal | int | str) -> int | str:
    quantity = _decimal(value)
    if quantity == quantity.to_integral_value():
        integer = int(quantity)
        if abs(integer) <= MAX_SAFE_JSON_INTEGER:
            return integer
    rendered = format(quantity, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in ("", "-0") else rendered


def _identity(row: dict[str, Any]) -> tuple[str, str, str | None]:
    return (
        row["batch_id"],
        row["unit"],
        row.get("packaging_configuration_id"),
    )


def _identity_sort_key(
    identity: tuple[str, str, str | None],
) -> tuple[str, str, bool, str]:
    batch_id, unit, packaging_configuration_id = identity
    return (
        batch_id,
        unit,
        packaging_configuration_id is not None,
        packaging_configuration_id or "",
    )


def canonical_audit_fingerprint(
    command: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
) -> str:
    """Hash domain equality, ignoring incidental row/evidence order."""
    canonical = {
        "actor": actor,
        "location_id": command["location_id"],
        "snapshot_token": command["snapshot_token"],
        "counts": sorted(
            (
                {
                    "batch_id": count["batch_id"],
                    "unit": count["unit"],
                    "packaging_configuration_id": count.get(
                        "packaging_configuration_id"
                    ),
                    "quantity": count["quantity"],
                }
                for count in command["counts"]
            ),
            key=lambda count: _identity_sort_key(_identity(count)),
        ),
        "unresolved_evidence": sorted(set(command.get("unresolved_evidence", []))),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class AuditObservationRepository:
    """Transaction-only writer and sanitized reader for audit observations."""

    def __init__(self, database):
        self.db = database
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        """Install uniqueness, recent-read, and deletion-reference indexes."""
        self.db.audit_observations.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="audit_observation_idempotency_key",
        )
        self.db.audit_observations.create_index(
            [("recorded_at", DESCENDING), ("_id", DESCENDING)],
            name="audit_observation_recent",
        )
        self.db.audit_observations.create_index(
            [
                ("location_id", ASCENDING),
                ("recorded_at", DESCENDING),
                ("_id", DESCENDING),
            ],
            name="audit_observation_by_location",
        )
        self.db.audit_observations.create_index(
            [("counts.batch_id", ASCENDING)],
            name="audit_observation_by_batch",
        )

    def _run_transaction(self, callback: Callable) -> Any:
        with self.db.client.start_session() as session:
            return session.with_transaction(
                callback,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )

    @staticmethod
    def _serialize(document: dict[str, Any]) -> dict[str, Any]:
        recorded_at = document.get("recorded_at")
        if isinstance(recorded_at, datetime):
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)
            recorded_at = recorded_at.isoformat()
        elif recorded_at is not None:
            recorded_at = str(recorded_at)

        counts = []
        for count in document.get("counts", []):
            if not isinstance(count, dict):
                continue
            counts.append({
                "batch_id": count.get("batch_id"),
                "unit": count.get("unit"),
                "packaging_configuration_id": count.get(
                    "packaging_configuration_id"
                ),
                "recorded_quantity": _quantity_json(
                    count.get("recorded_quantity", 0)
                ),
                "observed_quantity": _quantity_json(
                    count.get("observed_quantity", 0)
                ),
                "difference": _quantity_json(count.get("difference", 0)),
            })

        return {
            "observation_id": document.get("_id"),
            "location_id": document.get("location_id"),
            "snapshot_token": document.get("snapshot_token"),
            "recorded_at": recorded_at,
            "counts": counts,
            "unresolved_evidence": [
                evidence
                for evidence in document.get("unresolved_evidence", [])
                if isinstance(evidence, str)
            ],
        }

    def _existing_request(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        session,
    ) -> AuditObservationResult | None:
        existing = self.db.audit_observations.find_one(
            {"idempotency_key": idempotency_key},
            session=session,
        )
        if existing is None:
            return None
        if existing.get("request_fingerprint") != request_fingerprint:
            raise IdempotencyConflict(
                "idempotency key already belongs to a different audit observation"
            )
        return AuditObservationResult(
            self._serialize(existing),
            replayed=True,
        )

    def _recover_racing_idempotency(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        original_error: DuplicateKeyError,
    ) -> AuditObservationResult:
        existing = self.db.audit_observations.find_one(
            {"idempotency_key": idempotency_key}
        )
        if existing is None:
            raise original_error
        if existing.get("request_fingerprint") != request_fingerprint:
            raise IdempotencyConflict(
                "idempotency key already belongs to a different audit observation"
            ) from original_error
        return AuditObservationResult(
            self._serialize(existing),
            replayed=True,
        )

    def record(
        self,
        command: dict[str, Any],
        *,
        idempotency_key: str,
        actor: dict[str, str] | None = None,
    ) -> AuditObservationResult:
        """Append one reviewed count against the exact current snapshot."""
        request_fingerprint = canonical_audit_fingerprint(command, actor=actor)

        def write(session):
            existing = self._existing_request(
                idempotency_key,
                request_fingerprint,
                session,
            )
            if existing is not None:
                return existing

            location_id = command["location_id"]
            # Match inventory commands' Batch-then-Bin reservation order so
            # an audit racing a receipt does not introduce an inverted lock
            # order across the two collections.
            for batch_id in sorted({
                count["batch_id"] for count in command["counts"]
            }):
                if reserve_inventory_resource(
                    self.db.batch,
                    batch_id,
                    session,
                ) is None:
                    raise MissingBatch(batch_id)

            if reserve_inventory_resource(
                self.db.bin,
                location_id,
                session,
            ) is None:
                raise MissingBin(location_id)

            snapshot = read_audit_snapshot(
                self.db,
                location_id,
                session=session,
            )
            if snapshot is None:
                raise MissingBin(location_id)
            if snapshot["snapshot_token"] != command["snapshot_token"]:
                raise AuditSnapshotStale(snapshot["snapshot_token"])
            if snapshot["blockers"]:
                raise AuditSnapshotBlocked(snapshot["blockers"])

            expected = {
                _identity(holding): _decimal(holding["quantity"])
                for holding in snapshot["holdings"]
                if holding["supported"]
            }
            provided = {
                _identity(count): count
                for count in command["counts"]
            }
            missing = sorted(
                set(expected) - set(provided),
                key=_identity_sort_key,
            )
            if missing:
                raise AuditCountsRejected(
                    "missing-snapshot-holdings",
                    "counts must include every positive supported snapshot holding",
                )

            unexpected = sorted(
                set(provided) - set(expected),
                key=_identity_sort_key,
            )
            for identity in unexpected:
                count = provided[identity]
                if count["quantity"] <= 0:
                    raise AuditCountsRejected(
                        "unexpected-count-not-positive",
                        "a Batch absent from the snapshot must have a positive count",
                    )
                batch_id, unit, packaging_configuration_id = identity
                current = self.db.inventory_holdings.find_one(
                    {
                        "batch_id": batch_id,
                        "location_id": location_id,
                        "unit": unit,
                        "packaging_configuration_id": (
                            packaging_configuration_id
                        ),
                    },
                    {"quantity": 1},
                    session=session,
                )
                if _decimal(current.get("quantity") if current else None) != 0:
                    raise AuditCountsRejected(
                        "unexpected-holding-not-zero",
                        "a Batch absent from the snapshot must currently be zero",
                    )

            counts = []
            for identity in sorted(provided, key=_identity_sort_key):
                count = provided[identity]
                recorded_quantity = expected.get(identity, Decimal(0))
                observed_quantity = Decimal(count["quantity"])
                counts.append({
                    "batch_id": count["batch_id"],
                    "unit": count["unit"],
                    "packaging_configuration_id": count.get(
                        "packaging_configuration_id"
                    ),
                    "recorded_quantity": _decimal128(recorded_quantity),
                    "observed_quantity": _decimal128(observed_quantity),
                    "difference": _decimal128(_subtract(
                        observed_quantity,
                        recorded_quantity,
                    )),
                })

            # BSON datetime precision is milliseconds. Truncate before the
            # first response so a later read or idempotent replay is byte-for-
            # byte stable instead of losing sub-millisecond digits in MongoDB.
            now = datetime.now(timezone.utc)
            now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
            document = {
                "_id": f"AOB{uuid4().hex}",
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "location_id": location_id,
                "snapshot_token": snapshot["snapshot_token"],
                "recorded_at": now,
                "counts": counts,
                "unresolved_evidence": list(
                    command.get("unresolved_evidence", [])
                ),
            }
            if actor is not None:
                document.update({
                    "fact_id": document["_id"],
                    "fact_type": "inventory.audit-observation",
                    "envelope_version": 1,
                    "fact_schema": {
                        "name": "inventory.audit-observation",
                        "version": 1,
                    },
                    "actor": actor,
                    "command": {
                        "command_id": document["_id"],
                        "name": "inventory.audit-observation",
                        "idempotency_key": idempotency_key,
                        "request_fingerprint": request_fingerprint,
                    },
                    "causation": {},
                    "evidence": [],
                })
            self.db.audit_observations.insert_one(document, session=session)
            return AuditObservationResult(
                self._serialize(document),
                replayed=False,
            )

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            return self._recover_racing_idempotency(
                idempotency_key,
                request_fingerprint,
                error,
            )

    def observation(self, observation_id: str) -> dict[str, Any] | None:
        """Return one sanitized observation by stable public identifier."""
        document = self.db.audit_observations.find_one({"_id": observation_id})
        if document is None:
            return None
        observation = self._serialize(document)
        reconciliation = self.db.inventory_operations.find_one(
            {
                "kind": "reconciliation",
                "reconciles_observation_id": observation_id,
            },
            {"_id": 1},
        )
        if reconciliation is not None:
            observation["reconciled_by_operation_id"] = reconciliation["_id"]
        return observation

    def recent_observations(self, *, limit: int) -> list[dict[str, Any]]:
        """Return a bounded newest-first list without command-control fields."""
        bounded_limit = max(1, min(limit, 100))
        documents = self.db.audit_observations.find({}).sort([
            ("recorded_at", DESCENDING),
            ("_id", DESCENDING),
        ]).limit(bounded_limit)
        documents = list(documents)
        observation_ids = [document["_id"] for document in documents]
        reconciliations = {
            operation["reconciles_observation_id"]: operation["_id"]
            for operation in self.db.inventory_operations.find(
                {
                    "kind": "reconciliation",
                    "reconciles_observation_id": {"$in": observation_ids},
                },
                {"_id": 1, "reconciles_observation_id": 1},
            )
        } if observation_ids else {}
        observations = []
        for document in documents:
            observation = self._serialize(document)
            reconciled_by = reconciliations.get(document["_id"])
            if reconciled_by is not None:
                observation["reconciled_by_operation_id"] = reconciled_by
            observations.append(observation)
        return observations
