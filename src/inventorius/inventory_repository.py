"""MongoDB persistence for the append-only inventory ledger.

The operation collection is the source of truth.  ``inventory_holdings`` is a
replaceable projection, updated in the same transaction only to make ordinary
balance reads cheap.  This module intentionally has no path back to
``bin.contents``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Any, Callable
from uuid import uuid4

from bson.decimal128 import Decimal128
from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from inventorius.ledger import (
    HoldingKey,
    HoldingLeg,
    IdempotencyConflict,
    InsufficientHolding,
    InventoryOperation,
    OperationKind,
)


class MissingBin(ValueError):
    """The requested physical location was not present at commit time."""


class MissingBatch(ValueError):
    """The requested inventory identity was not present at commit time."""


class LedgerReferencedBin(ValueError):
    """A bin has immutable ledger history and therefore cannot be deleted."""


class LedgerReferencedBatch(ValueError):
    """A batch is named by inventory state or immutable evidence."""


@dataclass(frozen=True)
class RepositoryResult:
    result: dict[str, Any]
    replayed: bool


def canonical_fingerprint(command: dict[str, Any]) -> str:
    """Hash the validated command, rather than an incidental JSON encoding."""
    command = dict(command)
    # Repeated scans of the same external code and their order do not change
    # the capture command.  Preserve the user's spelling in stored evidence.
    if "observed_codes" in command:
        command["observed_codes"] = sorted(set(command["observed_codes"]))
    encoded = json.dumps(
        command,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _decimal128(value: Decimal | int | str) -> Decimal128:
    return Decimal128(str(Decimal(str(value))))


def _decimal(value: Decimal128 | Decimal | int | str | None) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal128):
        return value.to_decimal()
    return Decimal(str(value))


def _next_label(prefix: str, number: int) -> str:
    return f"{prefix}{number:06d}"


class InventoryRepository:
    """Transaction-only writer for inventory operations and holdings."""

    def __init__(self, database):
        self.db = database
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.db.inventory_operations.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="inventory_operation_idempotency_key",
        )
        self.db.inventory_holdings.create_index(
            [
                ("batch_id", ASCENDING),
                ("location_id", ASCENDING),
                ("unit", ASCENDING),
                ("packaging_configuration_id", ASCENDING),
            ],
            unique=True,
            name="inventory_holding_identity",
        )
        self.db.inventory_code_observations.create_index(
            [("code", ASCENDING), ("batch_id", ASCENDING)],
            name="observed_code_batch",
        )

    def _run_transaction(self, callback: Callable) -> Any:
        with self.db.client.start_session() as session:
            return session.with_transaction(
                callback,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )

    def _existing_request(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        session,
    ) -> RepositoryResult | None:
        existing = self.db.inventory_operations.find_one(
            {"idempotency_key": idempotency_key}, session=session
        )
        if existing is None:
            return None
        if existing["request_fingerprint"] != request_fingerprint:
            raise IdempotencyConflict(
                "idempotency key already belongs to a different command"
            )
        return RepositoryResult(existing["result"], replayed=True)

    def _recover_racing_idempotency(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        original_error: DuplicateKeyError,
    ) -> RepositoryResult:
        """Resolve the unique-index race after its aborted transaction ends."""
        existing = self.db.inventory_operations.find_one(
            {"idempotency_key": idempotency_key}
        )
        if existing is None:
            raise original_error
        if existing["request_fingerprint"] != request_fingerprint:
            raise IdempotencyConflict(
                "idempotency key already belongs to a different command"
            )
        return RepositoryResult(existing["result"], replayed=True)

    @staticmethod
    def _max_legacy_label_number(collection, prefix: str, session) -> int:
        maximum = 0
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
        for document in collection.find({}, {"_id": 1}, session=session):
            match = pattern.fullmatch(str(document["_id"]))
            if match:
                maximum = max(maximum, int(match.group(1)))
        return maximum

    def _allocate_label(self, prefix: str, collection, session) -> str:
        """Allocate a never-reused numeric label within the current transaction.

        The counter is deliberately separate from legacy ``admin`` documents.
        The one-time starting point merely avoids colliding with labels that
        already exist; it does not migrate or alter their legacy bookkeeping.
        """
        counter = self.db.inventory_counters.find_one({"_id": prefix}, session=session)
        if counter is None:
            # Initialization is the only legacy scan.  A competing first
            # capture can force a transaction retry, which then sees the
            # committed counter and takes the O(1) branch below.
            next_number = self._max_legacy_label_number(collection, prefix, session) + 1
            self.db.inventory_counters.update_one(
                {"_id": prefix},
                {"$setOnInsert": {"next_number": next_number}},
                upsert=True,
                session=session,
            )
        before = self.db.inventory_counters.find_one_and_update(
            {"_id": prefix},
            {"$inc": {"next_number": 1}},
            return_document=ReturnDocument.BEFORE,
            session=session,
        )
        return _next_label(prefix, before["next_number"])

    @staticmethod
    def _operation_document(
        operation: InventoryOperation,
        request_fingerprint: str,
        result: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "_id": operation.operation_id,
            "idempotency_key": operation.idempotency_key,
            "request_fingerprint": request_fingerprint,
            "kind": operation.kind.value,
            "legs": [
                {
                    "batch_id": leg.holding.batch_id,
                    "location_id": leg.holding.location_id,
                    "unit": leg.holding.unit,
                    "packaging_configuration_id": (
                        leg.holding.packaging_configuration_id
                    ),
                    "quantity": _decimal128(leg.amount),
                }
                for leg in operation.legs
            ],
            "created_at": now,
            "result": result,
        }

    def _apply_projection(self, operation: InventoryOperation, session, now: datetime) -> None:
        deltas: dict[HoldingKey, Decimal] = {}
        for leg in operation.legs:
            deltas[leg.holding] = deltas.get(leg.holding, Decimal(0)) + leg.amount

        for holding, delta in deltas.items():
            existing = self.db.inventory_holdings.find_one(
                {
                    "batch_id": holding.batch_id,
                    "location_id": holding.location_id,
                    "unit": holding.unit,
                    "packaging_configuration_id": holding.packaging_configuration_id,
                },
                session=session,
            )
            if _decimal(existing.get("quantity") if existing else None) + delta < 0:
                raise InsufficientHolding(
                    f"operation would make a holding negative: {holding}"
                )

        for holding, delta in deltas.items():
            identity = {
                "batch_id": holding.batch_id,
                "location_id": holding.location_id,
                "unit": holding.unit,
                "packaging_configuration_id": holding.packaging_configuration_id,
            }
            self.db.inventory_holdings.update_one(
                identity,
                {
                    "$inc": {"quantity": _decimal128(delta)},
                    "$set": {"updated_at": now},
                    "$setOnInsert": identity,
                },
                upsert=True,
                session=session,
            )

    def _reserve_bin_for_ledger_write(self, bin_id: str, session) -> dict[str, Any] | None:
        """Acquire the bin document's transactional write point.

        A capture needs the physical location to remain present through its
        commit.  Reading it is not enough: a concurrent delete could otherwise
        remove the document while the operation still names that location.  A
        temporary internal write marker makes capture and deletion conflict
        on the same document, so Mongo retries one transaction against the
        other's committed state.  It is removed before commit: this is a
        serialization point, not user-visible bin state.
        """
        token = uuid4().hex
        existing = self.db.bin.find_one_and_update(
            {"_id": bin_id},
            {"$set": {"_ledger_write_lock": token}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if existing is not None:
            self.db.bin.update_one(
                {"_id": bin_id, "_ledger_write_lock": token},
                {"$unset": {"_ledger_write_lock": ""}},
                session=session,
            )
        return existing

    def _reserve_batch_for_ledger_write(
        self, batch_id: str, session
    ) -> dict[str, Any] | None:
        """Keep a batch present through an operation's transaction commit.

        Batch deletion already refuses ledger history, but merely reading a
        batch would leave a narrow race before this operation writes that
        history.  This is the same transaction-local write point used for
        bins: it serializes a concurrent delete without creating durable
        application state.
        """
        token = uuid4().hex
        existing = self.db.batch.find_one_and_update(
            {"_id": batch_id},
            {"$set": {"_ledger_write_lock": token}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if existing is not None:
            self.db.batch.update_one(
                {"_id": batch_id, "_ledger_write_lock": token},
                {"$unset": {"_ledger_write_lock": ""}},
                session=session,
            )
        return existing

    def _bin_has_ledger_reference(self, bin_id: str, session) -> bool:
        """Whether any ledger record, including a zero holding, names a bin."""
        return (
            self.db.inventory_operations.find_one(
                {"legs.location_id": bin_id}, {"_id": 1}, session=session
            ) is not None
            or self.db.inventory_holdings.find_one(
                {"location_id": bin_id}, {"_id": 1}, session=session
            ) is not None
        )

    def _batch_has_inventory_reference(self, batch_id: str, session) -> bool:
        """Whether a batch is named by either legacy or ledger inventory data."""
        return any((
            self.db.bin.find_one(
                {f"contents.{batch_id}": {"$exists": True}},
                {"_id": 1},
                session=session,
            ),
            self.db.inventory_holdings.find_one(
                {"batch_id": batch_id}, {"_id": 1}, session=session
            ),
            self.db.inventory_operations.find_one(
                {"legs.batch_id": batch_id}, {"_id": 1}, session=session
            ),
            self.db.inventory_code_observations.find_one(
                {"batch_id": batch_id}, {"_id": 1}, session=session
            ),
        ))

    def delete_legacy_bin(self, bin_id: str, *, force: bool) -> bool:
        """Delete a genuinely legacy bin, or report that force is still needed.

        Ledger-referenced locations are never eligible for deletion.  This
        deliberately differs from a nonempty legacy ``contents`` map, which
        retains the old force-delete escape hatch until the legacy flows are
        retired.
        """
        def write(session):
            existing = self._reserve_bin_for_ledger_write(bin_id, session)
            if existing is None:
                raise MissingBin(bin_id)
            if self._bin_has_ledger_reference(bin_id, session):
                raise LedgerReferencedBin(bin_id)
            if existing.get("contents", {}) and not force:
                return False
            self.db.bin.delete_one({"_id": bin_id}, session=session)
            return True

        return self._run_transaction(write)

    def delete_legacy_batch(self, batch_id: str) -> None:
        """Delete a genuinely unreferenced batch, atomically with its checks.

        This shares the same batch write point as command execution.  Without
        it, a receipt could observe a batch and append an operation after a
        concurrent non-transactional delete had already removed it.
        """
        def write(session):
            if self._reserve_batch_for_ledger_write(batch_id, session) is None:
                raise MissingBatch(batch_id)
            if self._batch_has_inventory_reference(batch_id, session):
                raise LedgerReferencedBatch(batch_id)
            self.db.batch.delete_one({"_id": batch_id}, session=session)

        self._run_transaction(write)

    def post(
        self,
        operation: InventoryOperation,
        *,
        request_fingerprint: str,
        result: dict[str, Any],
    ) -> RepositoryResult:
        """Append one supported operation and update its holding projection."""
        def write(session):
            existing = self._existing_request(
                operation.idempotency_key, request_fingerprint, session
            )
            if existing is not None:
                return existing
            now = datetime.now(timezone.utc)
            self._apply_projection(operation, session, now)
            self.db.inventory_operations.insert_one(
                self._operation_document(operation, request_fingerprint, result, now),
                session=session,
            )
            return RepositoryResult(result, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            return self._recover_racing_idempotency(
                operation.idempotency_key, request_fingerprint, error
            )

    def execute_inventory_command(
        self,
        command: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> RepositoryResult:
        """Execute one validated physical inventory command atomically.

        This is intentionally narrower than :meth:`post`: callers specify a
        batch and the physical locations involved, never arbitrary ledger
        legs.  The public command is therefore easy to audit while the ledger
        retains the full immutable debit/credit representation.
        """
        request_fingerprint = canonical_fingerprint(command)

        def write(session):
            existing = self._existing_request(
                idempotency_key, request_fingerprint, session
            )
            if existing is not None:
                return existing

            batch_id = command["batch_id"]
            if self._reserve_batch_for_ledger_write(batch_id, session) is None:
                raise MissingBatch(batch_id)

            # Acquiring physical-location write points in a stable order keeps
            # simultaneous opposing transfers from relying on accidental lock
            # order.  Mongo may still retry a transaction; it will never
            # commit a ledger operation naming a deleted bin.
            bin_ids = sorted({
                bin_id
                for bin_id in (
                    command.get("location_id"),
                    command.get("source_location_id"),
                    command.get("destination_location_id"),
                )
                if bin_id is not None
            })
            for bin_id in bin_ids:
                if self._reserve_bin_for_ledger_write(bin_id, session) is None:
                    raise MissingBin(bin_id)

            kind = OperationKind(command["kind"])
            quantity = command["quantity"]
            unit = command["unit"]
            packaging_configuration_id = command.get("packaging_configuration_id")
            operation_id = f"OP{uuid4().hex}"
            location_id = command.get("location_id")
            source_location_id = command.get("source_location_id")
            destination_location_id = command.get("destination_location_id")

            if kind == OperationKind.RECEIVE:
                legs = (
                    HoldingLeg(
                        HoldingKey(
                            batch_id,
                            location_id,
                            unit,
                            packaging_configuration_id,
                        ),
                        quantity,
                    ),
                )
            elif kind == OperationKind.RELEASE:
                legs = (
                    HoldingLeg(
                        HoldingKey(
                            batch_id,
                            location_id,
                            unit,
                            packaging_configuration_id,
                        ),
                        -quantity,
                    ),
                )
            else:
                legs = (
                    HoldingLeg(
                        HoldingKey(
                            batch_id,
                            source_location_id,
                            unit,
                            packaging_configuration_id,
                        ),
                        -quantity,
                    ),
                    HoldingLeg(
                        HoldingKey(
                            batch_id,
                            destination_location_id,
                            unit,
                            packaging_configuration_id,
                        ),
                        quantity,
                    ),
                )

            operation = InventoryOperation(
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                kind=kind,
                legs=legs,
            )
            now = datetime.now(timezone.utc)
            result = {
                "operation_id": operation_id,
                "kind": kind.value,
                "batch_id": batch_id,
                "quantity": quantity,
                "unit": unit,
                "packaging_configuration_id": packaging_configuration_id,
            }
            if location_id is not None:
                result["location_id"] = location_id
            if source_location_id is not None:
                result["source_location_id"] = source_location_id
            if destination_location_id is not None:
                result["destination_location_id"] = destination_location_id

            self._apply_projection(operation, session, now)
            self.db.inventory_operations.insert_one(
                self._operation_document(operation, request_fingerprint, result, now),
                session=session,
            )
            return RepositoryResult(result, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            return self._recover_racing_idempotency(
                idempotency_key, request_fingerprint, error
            )

    def capture_intake(
        self,
        capture: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> RepositoryResult:
        """Atomically create the captured identity, evidence, receive, and holding."""
        request_fingerprint = canonical_fingerprint(capture)

        def write(session):
            existing = self._existing_request(
                idempotency_key, request_fingerprint, session
            )
            if existing is not None:
                return existing

            if self._reserve_bin_for_ledger_write(capture["bin_id"], session) is None:
                raise MissingBin(capture["bin_id"])

            sku_id = self._allocate_label("SKU", self.db.sku, session)
            batch_id = self._allocate_label("BAT", self.db.batch, session)
            operation_id = f"OP{uuid4().hex}"
            now = datetime.now(timezone.utc)
            observed_codes = capture.get("observed_codes", [])
            result = {
                "sku_id": sku_id,
                "batch_id": batch_id,
                "operation_id": operation_id,
                "bin_id": capture["bin_id"],
                "quantity": capture["quantity"],
                "unit": capture["unit"],
                "description": capture["description"],
                "observed_codes": observed_codes,
                "provisional": True,
            }

            self.db.sku.insert_one(
                {
                    "_id": sku_id,
                    "name": capture["description"],
                    "owned_codes": [],
                    "associated_codes": [],
                    "props": {
                        "_capture_status": "provisional",
                        "_captured_at": now.isoformat(),
                    },
                },
                session=session,
            )
            self.db.batch.insert_one(
                {
                    "_id": batch_id,
                    "sku_id": sku_id,
                    "name": capture["description"],
                    "owned_codes": [],
                    "associated_codes": [],
                    "props": {"_capture_status": "provisional"},
                },
                session=session,
            )
            if observed_codes:
                self.db.inventory_code_observations.insert_many(
                    [
                        {
                            "_id": f"OBS{uuid4().hex}",
                            "code": code,
                            "batch_id": batch_id,
                            "sku_id": sku_id,
                            "operation_id": operation_id,
                            "observed_at": now,
                        }
                        for code in observed_codes
                    ],
                    session=session,
                )

            operation = InventoryOperation(
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                kind=OperationKind.RECEIVE,
                legs=(
                    # Intake has no packaging configuration yet.
                    HoldingLeg(
                        HoldingKey(batch_id, capture["bin_id"], capture["unit"]),
                        capture["quantity"],
                    ),
                ),
            )
            self._apply_projection(operation, session, now)
            self.db.inventory_operations.insert_one(
                self._operation_document(operation, request_fingerprint, result, now),
                session=session,
            )
            return RepositoryResult(result, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            return self._recover_racing_idempotency(
                idempotency_key, request_fingerprint, error
            )
