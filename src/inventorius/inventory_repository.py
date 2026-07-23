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
from typing import Any, Callable
from uuid import uuid4

from bson.decimal128 import Decimal128
from pymongo import ASCENDING, DESCENDING
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
from inventorius.inventory_serialization import reserve_inventory_resource
from inventorius.resource_repository import PermanentIdentifierAllocator


MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991


class MissingBin(ValueError):
    """The requested physical location was not present at commit time."""


class MissingBatch(ValueError):
    """The requested inventory identity was not present at commit time."""


class MissingSku(ValueError):
    """The requested product identity was not present at commit time."""


class LedgerReferencedBin(ValueError):
    """A bin has immutable ledger history and therefore cannot be deleted."""


class LedgerReferencedBatch(ValueError):
    """A batch is named by inventory state or immutable evidence."""


class LedgerReferencedSku(ValueError):
    """A SKU is still named by inventory state, history, or a process."""


class MissingInventoryOperation(ValueError):
    """The requested immutable inventory receipt does not exist."""


class CorrectionRejected(ValueError):
    """A receipt cannot be corrected by the constrained replacement command."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


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


def _quantity_json(
    value: Decimal128 | Decimal | int | str | None,
) -> int | str | None:
    """Return a JSON value without silently rounding an exact BSON quantity."""
    if value is None:
        return None
    try:
        quantity = _decimal(value)
    except Exception:
        # Receipt reads must remain useful enough to expose malformed history as
        # a correction blocker.  Preserve the stored spelling rather than
        # crashing or inventing a numeric interpretation.
        return str(value)
    if not quantity.is_finite():
        return str(quantity)
    if quantity == quantity.to_integral_value():
        integer = int(quantity)
        if abs(integer) <= MAX_SAFE_JSON_INTEGER:
            return integer
    rendered = format(quantity, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in ("-0", "") else rendered


class InventoryRepository:
    """Transaction-only writer for inventory operations and holdings."""

    def __init__(self, database):
        self.db = database
        self.identifiers = PermanentIdentifierAllocator(database)
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.db.inventory_operations.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="inventory_operation_idempotency_key",
        )
        self.db.inventory_operations.create_index(
            [("created_at", DESCENDING), ("_id", DESCENDING)],
            name="inventory_operation_recent",
        )
        self.db.inventory_operations.create_index(
            [("corrects_operation_id", ASCENDING)],
            unique=True,
            partialFilterExpression={
                "kind": OperationKind.CORRECTION.value,
                "corrects_operation_id": {"$type": "string"},
            },
            name="inventory_operation_single_correction",
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

    @staticmethod
    def _sanitized_result(result: Any) -> dict[str, Any]:
        """Expose only stable receipt metadata, never command-control secrets."""
        if not isinstance(result, dict):
            return {}

        scalar_fields = {
            "operation_id",
            "kind",
            "batch_id",
            "sku_id",
            "bin_id",
            "location_id",
            "source_location_id",
            "destination_location_id",
            "unit",
            "packaging_configuration_id",
            "provisional",
            "created_sku",
            "description",
            "mode",
            "corrects_operation_id",
        }
        quantity_fields = {"quantity"}
        nested_state_fields = {"original_state", "intended_state"}
        sanitized: dict[str, Any] = {}
        for key in scalar_fields:
            value = result.get(key)
            if value is None and key not in result:
                continue
            if isinstance(value, (str, bool, int, float)) or value is None:
                sanitized[key] = value
        for key in quantity_fields:
            if key in result:
                sanitized[key] = _quantity_json(result[key])
        observed_codes = result.get("observed_codes")
        if isinstance(observed_codes, list):
            sanitized["observed_codes"] = [
                value for value in observed_codes if isinstance(value, str)
            ]
        for key in nested_state_fields:
            value = result.get(key)
            if isinstance(value, dict):
                nested: dict[str, Any] = {}
                for field in (
                    "batch_id",
                    "location_id",
                    "unit",
                    "packaging_configuration_id",
                ):
                    if field in value and (
                        isinstance(value[field], str) or value[field] is None
                    ):
                        nested[field] = value[field]
                if "quantity" in value:
                    nested["quantity"] = _quantity_json(value["quantity"])
                sanitized[key] = nested
        return sanitized

    @staticmethod
    def _original_receive_state(
        document: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Recognize the one receipt shape this correction slice can replace."""
        kind = document.get("kind")
        if kind == OperationKind.CORRECTION.value:
            return None, "correction-target"
        if kind not in {member.value for member in OperationKind}:
            return None, "malformed-history"
        if kind != OperationKind.RECEIVE.value:
            return None, "unsupported-operation-kind"

        legs = document.get("legs")
        if not isinstance(legs, list) or len(legs) != 1:
            return None, "unsupported-receipt-shape"
        leg = legs[0]
        if not isinstance(leg, dict):
            return None, "malformed-history"
        batch_id = leg.get("batch_id")
        location_id = leg.get("location_id")
        unit = leg.get("unit")
        package_id = leg.get("packaging_configuration_id")
        if not isinstance(batch_id, str) or not isinstance(location_id, str):
            return None, "malformed-history"
        if unit != "each":
            return None, "unsupported-unit"
        if package_id is not None:
            return None, "packaged-holding"
        try:
            quantity = _decimal(leg.get("quantity"))
        except Exception:
            return None, "malformed-history"
        if (
            not quantity.is_finite()
            or quantity <= 0
            or quantity != quantity.to_integral_value()
            or quantity > MAX_SAFE_JSON_INTEGER
        ):
            return None, "unsupported-quantity"
        return {
            "batch_id": batch_id,
            "location_id": location_id,
            "quantity": _quantity_json(quantity),
            "unit": unit,
            "packaging_configuration_id": None,
        }, None

    def _receipt(
        self,
        document: dict[str, Any],
        *,
        session=None,
        hydration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Render an immutable operation without internal command-control data."""
        legs = []
        batch_ids = set()
        raw_legs = document.get("legs")
        if isinstance(raw_legs, list):
            for raw_leg in raw_legs:
                if not isinstance(raw_leg, dict):
                    continue
                batch_id = raw_leg.get("batch_id")
                if isinstance(batch_id, str):
                    batch_ids.add(batch_id)
                legs.append({
                    "batch_id": batch_id,
                    "location_id": raw_leg.get("location_id"),
                    "unit": raw_leg.get("unit"),
                    "packaging_configuration_id": raw_leg.get(
                        "packaging_configuration_id"
                    ),
                    "quantity": (
                        _quantity_json(raw_leg["quantity"])
                        if "quantity" in raw_leg
                        else None
                    ),
                })

        if hydration is None:
            corrected_by = self.db.inventory_operations.find_one(
                {
                    "kind": OperationKind.CORRECTION.value,
                    "corrects_operation_id": document.get("_id"),
                },
                {"_id": 1},
                session=session,
            )
            corrected_by_id = (
                corrected_by["_id"] if corrected_by is not None else None
            )
        else:
            corrected_by_id = hydration["corrected_by"].get(document.get("_id"))
        _, blocker = self._original_receive_state(document)
        if corrected_by_id is not None:
            blocker = "already-corrected"

        current_holdings = []
        if batch_ids:
            if hydration is None:
                holdings = self.db.inventory_holdings.find(
                    {"batch_id": {"$in": sorted(batch_ids)}},
                    session=session,
                )
            else:
                holdings = [
                    holding
                    for batch_id in batch_ids
                    for holding in hydration["holdings"].get(batch_id, ())
                ]
            for holding in holdings:
                current_holdings.append({
                    "batch_id": holding.get("batch_id"),
                    "location_id": holding.get("location_id"),
                    "unit": holding.get("unit"),
                    "packaging_configuration_id": holding.get(
                        "packaging_configuration_id"
                    ),
                    "quantity": _quantity_json(holding.get("quantity")),
                })
            current_holdings.sort(key=lambda holding: (
                str(holding["batch_id"]),
                str(holding["location_id"]),
                str(holding["unit"]),
                str(holding["packaging_configuration_id"]),
            ))

        batches = []
        if batch_ids:
            if hydration is None:
                batch_documents = list(self.db.batch.find(
                    {"_id": {"$in": sorted(batch_ids)}},
                    {"_id": 1, "name": 1, "sku_id": 1},
                    session=session,
                ))
                sku_ids = {
                    batch.get("sku_id")
                    for batch in batch_documents
                    if isinstance(batch.get("sku_id"), str)
                }
                sku_names = {
                    sku["_id"]: sku.get("name")
                    for sku in self.db.sku.find(
                        {"_id": {"$in": sorted(sku_ids)}},
                        {"_id": 1, "name": 1},
                        session=session,
                    )
                } if sku_ids else {}
                batch_metadata = {
                    batch["_id"]: {
                        "batch_id": batch["_id"],
                        "batch_name": batch.get("name"),
                        "sku_id": batch.get("sku_id"),
                        "sku_name": sku_names.get(batch.get("sku_id")),
                    }
                    for batch in batch_documents
                }
            else:
                batch_metadata = hydration["batches"]
            batches = [
                batch_metadata[batch_id]
                for batch_id in sorted(batch_ids)
                if batch_id in batch_metadata
            ]

        created_at = document.get("created_at")
        if isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at = created_at.isoformat()
        elif created_at is not None:
            created_at = str(created_at)

        return {
            "operation_id": document.get("_id"),
            "kind": document.get("kind"),
            "created_at": created_at,
            "legs": legs,
            "result": self._sanitized_result(document.get("result")),
            "batches": batches,
            "current_holdings": current_holdings,
            "corrects_operation_id": document.get("corrects_operation_id"),
            "corrected_by_operation_id": corrected_by_id,
            "correction": {
                "correctable": blocker is None,
                "blocker": blocker,
            },
        }

    def _hydrate_receipts(
        self,
        documents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Batch the bounded list's related reads for the small production VPS."""
        operation_ids = [
            document["_id"] for document in documents if "_id" in document
        ]
        batch_ids = {
            leg.get("batch_id")
            for document in documents
            for leg in (
                document.get("legs")
                if isinstance(document.get("legs"), list)
                else ()
            )
            if isinstance(leg, dict) and isinstance(leg.get("batch_id"), str)
        }
        corrected_by = {
            correction["corrects_operation_id"]: correction["_id"]
            for correction in self.db.inventory_operations.find(
                {
                    "kind": OperationKind.CORRECTION.value,
                    "corrects_operation_id": {"$in": operation_ids},
                },
                {"_id": 1, "corrects_operation_id": 1},
            )
        } if operation_ids else {}

        holdings_by_batch: dict[str, list[dict[str, Any]]] = {}
        if batch_ids:
            for holding in self.db.inventory_holdings.find(
                {"batch_id": {"$in": sorted(batch_ids)}}
            ):
                holdings_by_batch.setdefault(holding["batch_id"], []).append(holding)

        batch_documents = list(self.db.batch.find(
            {"_id": {"$in": sorted(batch_ids)}},
            {"_id": 1, "name": 1, "sku_id": 1},
        )) if batch_ids else []
        sku_ids = {
            batch.get("sku_id")
            for batch in batch_documents
            if isinstance(batch.get("sku_id"), str)
        }
        sku_names = {
            sku["_id"]: sku.get("name")
            for sku in self.db.sku.find(
                {"_id": {"$in": sorted(sku_ids)}},
                {"_id": 1, "name": 1},
            )
        } if sku_ids else {}
        batches = {
            batch["_id"]: {
                "batch_id": batch["_id"],
                "batch_name": batch.get("name"),
                "sku_id": batch.get("sku_id"),
                "sku_name": sku_names.get(batch.get("sku_id")),
            }
            for batch in batch_documents
        }
        return {
            "corrected_by": corrected_by,
            "holdings": holdings_by_batch,
            "batches": batches,
        }

    def recent_receipts(self, *, limit: int) -> list[dict[str, Any]]:
        """Return a bounded newest-first view of durable inventory receipts."""
        bounded_limit = max(1, min(limit, 100))
        documents = list(self.db.inventory_operations.find({}).sort([
            ("created_at", DESCENDING),
            ("_id", DESCENDING),
        ]).limit(bounded_limit))
        hydration = self._hydrate_receipts(documents)
        return [
            self._receipt(document, hydration=hydration)
            for document in documents
        ]

    def receipt(self, operation_id: str) -> dict[str, Any] | None:
        document = self.db.inventory_operations.find_one({"_id": operation_id})
        return None if document is None else self._receipt(document)

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
        if existing.get("request_fingerprint") != request_fingerprint:
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
        if existing.get("request_fingerprint") != request_fingerprint:
            raise IdempotencyConflict(
                "idempotency key already belongs to a different command"
            )
        return RepositoryResult(existing["result"], replayed=True)

    @staticmethod
    def _operation_document(
        operation: InventoryOperation,
        request_fingerprint: str,
        result: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        document = {
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
        if operation.corrects_operation_id is not None:
            document["corrects_operation_id"] = operation.corrects_operation_id
        return document

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
        return reserve_inventory_resource(self.db.bin, bin_id, session)

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
        return reserve_inventory_resource(self.db.batch, batch_id, session)

    def _reserve_sku_for_ledger_write(
        self, sku_id: str, session
    ) -> dict[str, Any] | None:
        """Keep an existing SKU present while intake creates its new Batch."""
        return reserve_inventory_resource(self.db.sku, sku_id, session)

    def _bin_has_ledger_reference(self, bin_id: str, session) -> bool:
        """Whether durable inventory or audit history names a bin."""
        return (
            self.db.inventory_operations.find_one(
                {"legs.location_id": bin_id}, {"_id": 1}, session=session
            ) is not None
            or self.db.inventory_holdings.find_one(
                {"location_id": bin_id}, {"_id": 1}, session=session
            ) is not None
            or self.db.audit_observations.find_one(
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
            self.db.audit_observations.find_one(
                {"counts.batch_id": batch_id}, {"_id": 1}, session=session
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
            # A physical label must never acquire a new meaning.  New Bin
            # creation already has a permanent claim; this also tombstones
            # bins that predate that allocator before removing their document.
            self.identifiers.preserve("BIN", bin_id, session)
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
            self.identifiers.preserve("BAT", batch_id, session)
            self.db.batch.delete_one({"_id": batch_id}, session=session)

        self._run_transaction(write)

    def _sku_reference_reason(self, sku_id: str, session) -> str | None:
        if self.db.bin.find_one(
            {f"contents.{sku_id}": {"$exists": True}}, {"_id": 1}, session=session
        ) is not None:
            return "legacy bin contents"
        if self.db.batch.find_one({"sku_id": sku_id}, {"_id": 1}, session=session) is not None:
            return "linked batches"
        if self.db.process_definition.find_one({
            "$or": [
                {"revisions.inputs.sku_id": sku_id},
                {"revisions.outputs.sku_id": sku_id},
            ]
        }, {"_id": 1}, session=session) is not None:
            return "process definitions"
        return None

    def delete_legacy_sku(self, sku_id: str) -> None:
        """Delete an unreferenced SKU using intake's serialization point."""
        def write(session):
            if self._reserve_sku_for_ledger_write(sku_id, session) is None:
                raise MissingSku(sku_id)
            reference_reason = self._sku_reference_reason(sku_id, session)
            if reference_reason is not None:
                raise LedgerReferencedSku(reference_reason)
            self.identifiers.preserve("SKU", sku_id, session)
            self.db.sku.delete_one({"_id": sku_id}, session=session)

        self._run_transaction(write)

    def post(
        self,
        operation: InventoryOperation,
        *,
        request_fingerprint: str,
        result: dict[str, Any],
    ) -> RepositoryResult:
        """Append one supported operation and update its holding projection."""
        if operation.kind == OperationKind.CORRECTION:
            raise ValueError(
                "correction must use the constrained correct_inventory_operation command"
            )

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
            batch_document = self._reserve_batch_for_ledger_write(batch_id, session)
            if batch_document is None:
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
            observed_codes = command.get("observed_codes", [])
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
            if kind == OperationKind.RECEIVE and "observed_codes" in command:
                result["observed_codes"] = observed_codes
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
            if observed_codes:
                self.db.inventory_code_observations.insert_many(
                    [
                        {
                            "_id": f"OBS{uuid4().hex}",
                            "code": code,
                            "batch_id": batch_id,
                            "sku_id": batch_document.get("sku_id"),
                            "operation_id": operation_id,
                            "observed_at": now,
                        }
                        for code in observed_codes
                    ],
                    session=session,
                )
            return RepositoryResult(result, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            return self._recover_racing_idempotency(
                idempotency_key, request_fingerprint, error
            )

    def correct_inventory_operation(
        self,
        original_operation_id: str,
        intended_state: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> RepositoryResult:
        """Replace one simple intake receipt with an explicit compensating fact.

        The original receipt remains immutable.  This command is deliberately
        narrower than the internal correction operation: only one uncorrected,
        positive, unpackaged ``each`` receive can be replaced, and the server
        derives every signed leg from that receipt plus the intended state.
        """
        fingerprint_command = {
            "kind": OperationKind.CORRECTION.value,
            "mode": "replace-receipt",
            "corrects_operation_id": original_operation_id,
            "intended_state": intended_state,
        }
        request_fingerprint = canonical_fingerprint(fingerprint_command)

        def write(session):
            existing = self._existing_request(
                idempotency_key, request_fingerprint, session
            )
            if existing is not None:
                return existing

            original = self.db.inventory_operations.find_one(
                {"_id": original_operation_id},
                session=session,
            )
            if original is None:
                raise MissingInventoryOperation(original_operation_id)
            original_state, blocker = self._original_receive_state(original)
            if blocker is not None:
                raise CorrectionRejected(
                    blocker,
                    "the selected receipt cannot be replaced by this correction",
                )

            if self.db.inventory_operations.find_one(
                {
                    "kind": OperationKind.CORRECTION.value,
                    "corrects_operation_id": original_operation_id,
                },
                {"_id": 1},
                session=session,
            ) is not None:
                raise CorrectionRejected(
                    "already-corrected",
                    "the selected receipt already has a correction",
                )

            batch_id = original_state["batch_id"]
            if self._reserve_batch_for_ledger_write(batch_id, session) is None:
                raise MissingBatch(batch_id)

            involved_bins = sorted({
                original_state["location_id"],
                intended_state["location_id"],
            })
            for bin_id in involved_bins:
                if self._reserve_bin_for_ledger_write(bin_id, session) is None:
                    raise MissingBin(bin_id)

            # Re-read after acquiring the same write points used by other
            # inventory commands.  History is immutable, but this makes the
            # shape/balance decision explicit inside the serialized boundary.
            original = self.db.inventory_operations.find_one(
                {"_id": original_operation_id},
                session=session,
            )
            original_state, blocker = self._original_receive_state(original)
            if blocker is not None:
                raise CorrectionRejected(
                    blocker,
                    "the selected receipt cannot be replaced by this correction",
                )
            if self.db.inventory_operations.find_one(
                {
                    "kind": OperationKind.CORRECTION.value,
                    "corrects_operation_id": original_operation_id,
                },
                {"_id": 1},
                session=session,
            ) is not None:
                raise CorrectionRejected(
                    "already-corrected",
                    "the selected receipt already has a correction",
                )

            normalized_intended_state = {
                "batch_id": batch_id,
                "location_id": intended_state["location_id"],
                "quantity": intended_state["quantity"],
                "unit": "each",
                "packaging_configuration_id": None,
            }
            if (
                normalized_intended_state["location_id"]
                == original_state["location_id"]
                and Decimal(normalized_intended_state["quantity"])
                == Decimal(str(original_state["quantity"]))
            ):
                raise CorrectionRejected(
                    "unchanged-intended-state",
                    "the intended state is identical to the original receipt",
                )

            original_holding = HoldingKey(
                batch_id,
                original_state["location_id"],
                "each",
                None,
            )
            intended_holding = HoldingKey(
                batch_id,
                normalized_intended_state["location_id"],
                "each",
                None,
            )
            deltas: dict[HoldingKey, Decimal] = {}
            deltas[original_holding] = -Decimal(str(original_state["quantity"]))
            if normalized_intended_state["quantity"] > 0:
                deltas[intended_holding] = (
                    deltas.get(intended_holding, Decimal(0))
                    + Decimal(normalized_intended_state["quantity"])
                )
            legs = tuple(
                HoldingLeg(holding, amount)
                for holding, amount in deltas.items()
                if amount != 0
            )

            operation_id = f"OP{uuid4().hex}"
            operation = InventoryOperation(
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                kind=OperationKind.CORRECTION,
                legs=legs,
                corrects_operation_id=original_operation_id,
            )
            now = datetime.now(timezone.utc)
            result = {
                "operation_id": operation_id,
                "kind": OperationKind.CORRECTION.value,
                "mode": "replace-receipt",
                "corrects_operation_id": original_operation_id,
                "batch_id": batch_id,
                "original_state": original_state,
                "intended_state": normalized_intended_state,
            }
            self._apply_projection(operation, session, now)
            self.db.inventory_operations.insert_one(
                self._operation_document(
                    operation,
                    request_fingerprint,
                    result,
                    now,
                ),
                session=session,
            )
            return RepositoryResult(result, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            # One unique index protects idempotency; another independently
            # guarantees one correction per original.  Recover both races into
            # stable domain outcomes rather than exposing a Mongo error.
            existing = self.db.inventory_operations.find_one(
                {"idempotency_key": idempotency_key}
            )
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise IdempotencyConflict(
                        "idempotency key already belongs to a different command"
                    ) from error
                return RepositoryResult(existing["result"], replayed=True)
            if self.db.inventory_operations.find_one({
                "kind": OperationKind.CORRECTION.value,
                "corrects_operation_id": original_operation_id,
            }) is not None:
                raise CorrectionRejected(
                    "already-corrected",
                    "the selected receipt already has a correction",
                ) from error
            raise

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

            description = capture.get("description")
            created_sku = description is not None
            if created_sku:
                sku_id = self.identifiers.allocate("SKU", session)
                sku_document = None
            else:
                sku_id = capture["sku_id"]
                sku_document = self._reserve_sku_for_ledger_write(sku_id, session)
                if sku_document is None:
                    raise MissingSku(sku_id)

            batch_id = self.identifiers.allocate("BAT", session)
            operation_id = f"OP{uuid4().hex}"
            now = datetime.now(timezone.utc)
            observed_codes = capture.get("observed_codes", [])
            batch_name = (
                description
                if description is not None
                else sku_document.get("name") or sku_id
            )
            result = {
                "sku_id": sku_id,
                "batch_id": batch_id,
                "operation_id": operation_id,
                "bin_id": capture["bin_id"],
                "quantity": capture["quantity"],
                "unit": capture["unit"],
                "observed_codes": observed_codes,
                "provisional": True,
                "created_sku": created_sku,
            }
            if description is not None:
                result["description"] = description

            if created_sku:
                self.db.sku.insert_one(
                    {
                        "_id": sku_id,
                        "name": description,
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
                    "name": batch_name,
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
