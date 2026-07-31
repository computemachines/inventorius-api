"""Transactional creation and permanent identifiers for physical resources.

Bins, SKUs, and Batches share one identity boundary.  Every allocated label is
claimed permanently in ``resource_identifiers`` in the same transaction that
creates the resource (or the intake operation that creates it).  The older
``admin`` and ``inventory_counters`` collections remain synchronized
projections during the migration, but neither is allowed to allocate from a
separate namespace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable
from uuid import uuid4

from pymongo import ASCENDING, ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from inventorius.data_models import Batch, Bin, Sku
from inventorius.util import IdentifierSpaceExhausted, MAX_IDENTIFIER_SUFFIX


RESOURCE_COLLECTIONS = {
    "BIN": "bin",
    "SKU": "sku",
    "BAT": "batch",
}
RESOURCE_COMMAND_KINDS = {
    "BIN": "create-bin",
    "SKU": "create-sku",
    "BAT": "create-batch",
}
ALLOCATOR_MARKER = "resource-identifiers-v1"


class ResourceIdempotencyConflict(ValueError):
    """An idempotency key was reused for a different resource command."""


class ResourceIdentifierAlreadyUsed(ValueError):
    """A resource identifier is live or has existed in the past."""


class MissingResourceReference(ValueError):
    """A resource command references another resource that does not exist."""

    def __init__(self, prefix: str, identifier: str):
        self.prefix = prefix
        self.identifier = identifier
        super().__init__(identifier)


@dataclass(frozen=True)
class ResourceCreationResult:
    state: dict[str, Any]
    replayed: bool


def _fingerprint(command: dict[str, Any]) -> str:
    encoded = json.dumps(
        command,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_identifier(prefix: str, number: int) -> str:
    return f"{prefix}{number:06d}"


def _valid_suffix(prefix: str, identifier: object) -> int | None:
    match = re.fullmatch(rf"{re.escape(prefix)}(\d{{1,6}})", str(identifier))
    if match is None:
        return None
    number = int(match.group(1))
    if number > MAX_IDENTIFIER_SUFFIX:
        return None
    return number


def _counter_value(value: object, default: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(number, MAX_IDENTIFIER_SUFFIX + 1))


def _reserved_floor(value: object, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(number, MAX_IDENTIFIER_SUFFIX + 1))


class PermanentIdentifierAllocator:
    """One transactional, never-reusing namespace for BIN, SKU, and BAT."""

    def __init__(self, database):
        self.db = database
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.db.resource_identifiers.create_index(
            [("prefix", ASCENDING), ("number", ASCENDING)],
            unique=True,
            name="resource_identifier_number",
        )

    @staticmethod
    def _collection_name(prefix: str) -> str:
        try:
            return RESOURCE_COLLECTIONS[prefix]
        except KeyError as error:
            raise ValueError(f"unsupported resource prefix: {prefix}") from error

    def _known_numbers(self, prefix: str, session) -> tuple[set[int], dict | None]:
        collection = self.db[self._collection_name(prefix)]
        live_numbers = {
            number
            for document in collection.find({}, {"_id": 1}, session=session)
            if (number := _valid_suffix(prefix, document.get("_id"))) is not None
        }
        claimed_numbers: set[int] = set()
        for document in self.db.resource_identifiers.find(
            {
                "$or": [
                    {"prefix": prefix},
                    {"_id": {"$regex": rf"^{re.escape(prefix)}\d{{1,6}}$"}},
                ]
            },
            {"number": 1},
            session=session,
        ):
            try:
                number = int(document["number"])
            except (KeyError, TypeError, ValueError):
                number = _valid_suffix(prefix, document.get("_id"))
            if number is not None and 0 <= number <= MAX_IDENTIFIER_SUFFIX:
                claimed_numbers.add(number)

        admin = self.db.admin.find_one({"_id": prefix}, session=session)
        admin_numbers: set[int] = set()
        if admin is not None:
            used = admin.get("used", [])
            if used is None:
                used_values = []
            elif isinstance(used, (list, tuple, set)):
                used_values = used
            else:
                # Some hand-edited/partial legacy documents stored the one
                # known number as a scalar.  Treat that as a recoverable
                # singleton rather than erasing a permanent physical label.
                used_values = [used]
            for value in used_values:
                if isinstance(value, int) and not isinstance(value, bool):
                    number = value
                elif isinstance(value, str) and value.isdigit():
                    number = int(value)
                elif isinstance(value, str):
                    number = _valid_suffix(prefix, value)
                else:
                    number = None
                if number is None:
                    raise ValueError(
                        f"cannot safely migrate malformed {prefix} admin.used"
                    )
                if 0 <= number <= MAX_IDENTIFIER_SUFFIX:
                    admin_numbers.add(number)

        return live_numbers | claimed_numbers | admin_numbers, admin

    @staticmethod
    def _admin_next(prefix: str, admin: dict | None) -> int:
        if admin is None:
            return 1
        if admin.get("exhausted"):
            return MAX_IDENTIFIER_SUFFIX + 1
        match = re.fullmatch(
            rf"{re.escape(prefix)}(\d+)",
            str(admin.get("next")),
        )
        if match is None:
            return 1
        return min(int(match.group(1)), MAX_IDENTIFIER_SUFFIX + 1)

    def _backfill_claims(
        self,
        prefix: str,
        known_numbers: set[int],
        session,
    ) -> None:
        now = datetime.now(timezone.utc)
        existing_by_number: set[int] = set()
        existing_by_id: set[str] = set()
        for document in self.db.resource_identifiers.find(
            {
                "$or": [
                    {"prefix": prefix},
                    {"_id": {"$regex": rf"^{re.escape(prefix)}\d{{1,6}}$"}},
                ]
            },
            {"prefix": 1, "number": 1},
            session=session,
        ):
            existing_by_id.add(str(document["_id"]))
            try:
                number = int(document["number"])
            except (KeyError, TypeError, ValueError):
                continue
            if document.get("prefix") == prefix:
                existing_by_number.add(number)

        writes = []
        for number in sorted(known_numbers):
            if number in existing_by_number:
                continue
            identifier = _canonical_identifier(prefix, number)
            if identifier in existing_by_id:
                writes.append(UpdateOne(
                    {"_id": identifier},
                    {
                        "$set": {
                            "prefix": prefix,
                            "number": number,
                            "migration_source": "repaired-legacy-identity",
                        },
                        "$setOnInsert": {"allocated_at": now},
                    },
                ))
            else:
                writes.append(UpdateOne(
                    {"prefix": prefix, "number": number},
                    {
                        "$setOnInsert": {
                            "_id": identifier,
                            "prefix": prefix,
                            "number": number,
                            "allocated_at": now,
                            "migration_source": "known-legacy-identity",
                        }
                    },
                    upsert=True,
                ))
        if writes:
            self.db.resource_identifiers.bulk_write(
                writes,
                ordered=False,
                session=session,
            )

    def _project_state(
        self,
        prefix: str,
        *,
        next_number: int,
        known_numbers: set[int],
        session,
    ) -> None:
        exhausted = next_number > MAX_IDENTIFIER_SUFFIX
        self.db.inventory_counters.update_one(
            {"_id": prefix},
            {
                "$set": {
                    "next_number": next_number,
                    "managed_by": ALLOCATOR_MARKER,
                }
            },
            upsert=True,
            session=session,
        )
        self.db.admin.update_one(
            {"_id": prefix},
            {
                "$set": {
                    "used": sorted(known_numbers),
                    "next": (
                        None
                        if exhausted
                        else _canonical_identifier(prefix, next_number)
                    ),
                    "exhausted": exhausted,
                    "managed_by": ALLOCATOR_MARKER,
                },
            },
            upsert=True,
            session=session,
        )

    def ensure_state(self, prefix: str, session) -> dict[str, Any]:
        """Reconcile every historical counter source into the shared state.

        ``inventory_counters`` did not retain individual claims.  Until a
        counter has our marker, all numbers below its next value are therefore
        conservatively reserved.  Old ``admin`` documents without a ``used``
        list receive the same treatment.  This loses gaps rather than allowing
        an old physical label to acquire a new meaning.
        """
        self._collection_name(prefix)
        counter = self.db.identifier_counters.find_one(
            {"_id": prefix}, session=session
        )
        inventory_counter = self.db.inventory_counters.find_one(
            {"_id": prefix}, session=session
        )
        admin = self.db.admin.find_one({"_id": prefix}, session=session)

        # Once all three projections carry the marker, every writer in this
        # codebase advances them in the same transaction.  Avoid turning each
        # later allocation or compatibility preview into a full migration scan.
        if (
            counter is not None
            and inventory_counter is not None
            and admin is not None
            and counter.get("managed_by") == ALLOCATOR_MARKER
            and inventory_counter.get("managed_by") == ALLOCATOR_MARKER
            and admin.get("managed_by") == ALLOCATOR_MARKER
        ):
            return counter

        known_numbers, admin = self._known_numbers(prefix, session)

        identifier_next = _counter_value(
            counter.get("next_number") if counter else None
        )
        inventory_next = _counter_value(
            inventory_counter.get("next_number") if inventory_counter else None
        )
        admin_next = self._admin_next(prefix, admin)
        known_next = max(known_numbers) + 1 if known_numbers else 1
        next_number = max(
            identifier_next,
            inventory_next,
            admin_next,
            known_next,
        )

        legacy_reserved_below = _reserved_floor(
            counter.get("legacy_reserved_below", 0) if counter else 0,
        )
        if (
            counter is not None
            and counter.get("managed_by") != ALLOCATOR_MARKER
        ):
            legacy_reserved_below = max(
                legacy_reserved_below, identifier_next
            )
        if (
            inventory_counter is not None
            and inventory_counter.get("managed_by") != ALLOCATOR_MARKER
        ):
            legacy_reserved_below = max(
                legacy_reserved_below, inventory_next
            )
        if admin is not None and admin.get("managed_by") != ALLOCATOR_MARKER:
            legacy_reserved_below = max(legacy_reserved_below, admin_next)

        self.db.identifier_counters.update_one(
            {"_id": prefix},
            {
                "$set": {
                    "next_number": next_number,
                    "legacy_reserved_below": legacy_reserved_below,
                    "managed_by": ALLOCATOR_MARKER,
                }
            },
            upsert=True,
            session=session,
        )
        self._backfill_claims(prefix, known_numbers, session)
        self._project_state(
            prefix,
            next_number=next_number,
            known_numbers=known_numbers,
            session=session,
        )
        return self.db.identifier_counters.find_one(
            {"_id": prefix}, session=session
        )

    def _claim_identifier(
        self,
        prefix: str,
        identifier: str,
        number: int,
        session,
    ) -> None:
        self.db.resource_identifiers.insert_one(
            {
                "_id": identifier,
                "prefix": prefix,
                "number": number,
                "allocated_at": datetime.now(timezone.utc),
            },
            session=session,
        )

    def _project_claim(
        self,
        prefix: str,
        number: int,
        next_number: int,
        session,
    ) -> None:
        self.db.inventory_counters.update_one(
            {"_id": prefix},
            {
                "$set": {
                    "next_number": next_number,
                    "managed_by": ALLOCATOR_MARKER,
                }
            },
            session=session,
        )
        self.db.admin.update_one(
            {"_id": prefix},
            {
                "$addToSet": {"used": number},
                "$set": {
                    "next": (
                        None
                        if next_number > MAX_IDENTIFIER_SUFFIX
                        else _canonical_identifier(prefix, next_number)
                    ),
                    "exhausted": next_number > MAX_IDENTIFIER_SUFFIX,
                    "managed_by": ALLOCATOR_MARKER,
                },
            },
            upsert=True,
            session=session,
        )

    def allocate(
        self,
        prefix: str,
        session,
        *,
        requested_id: str | None = None,
    ) -> str:
        counter = self.ensure_state(prefix, session)

        if requested_id is not None:
            number = _valid_suffix(prefix, requested_id)
            if number is None:
                raise ValueError(f"invalid canonical {prefix} identifier")
            identifier = _canonical_identifier(prefix, number)
            # Generated labels have always begun at one.  Even a legacy
            # monotonic floor cannot imply that zero was allocated; a real
            # claim/live/admin record still prevents reusing zero normally.
            if (
                number != 0
                and number < int(counter.get("legacy_reserved_below", 0))
            ):
                raise ResourceIdentifierAlreadyUsed(requested_id)
            if self.db.resource_identifiers.find_one(
                {"prefix": prefix, "number": number},
                {"_id": 1},
                session=session,
            ) is not None:
                raise ResourceIdentifierAlreadyUsed(requested_id)
            collection = self.db[self._collection_name(prefix)]
            if collection.find_one(
                {"_id": identifier}, {"_id": 1}, session=session
            ) is not None:
                raise ResourceIdentifierAlreadyUsed(requested_id)

            self._claim_identifier(prefix, identifier, number, session)
            self.db.identifier_counters.update_one(
                {"_id": prefix},
                {"$max": {"next_number": number + 1}},
                session=session,
            )
            current = self.db.identifier_counters.find_one(
                {"_id": prefix}, session=session
            )
            self._project_claim(
                prefix, number, int(current["next_number"]), session
            )
            return identifier

        before = self.db.identifier_counters.find_one_and_update(
            {
                "_id": prefix,
                "next_number": {"$lte": MAX_IDENTIFIER_SUFFIX},
            },
            {"$inc": {"next_number": 1}},
            return_document=ReturnDocument.BEFORE,
            session=session,
        )
        if before is None:
            raise IdentifierSpaceExhausted(prefix)

        number = int(before["next_number"])
        identifier = _canonical_identifier(prefix, number)
        self._claim_identifier(prefix, identifier, number, session)
        self._project_claim(prefix, number, number + 1, session)
        return identifier

    def next_available_id(self, prefix: str, session) -> str:
        counter = self.ensure_state(prefix, session)
        number = int(counter["next_number"])
        if number > MAX_IDENTIFIER_SUFFIX:
            raise IdentifierSpaceExhausted(prefix)
        return _canonical_identifier(prefix, number)

    def preserve(self, prefix: str, identifier: str, session) -> None:
        """Permanently tombstone a resource that predates this allocator."""
        self.ensure_state(prefix, session)
        number = _valid_suffix(prefix, identifier)
        if number is None:
            raise ValueError(f"invalid canonical {prefix} identifier")
        canonical_id = _canonical_identifier(prefix, number)
        self.db.resource_identifiers.update_one(
            {"prefix": prefix, "number": number},
            {
                "$setOnInsert": {
                    "_id": canonical_id,
                    "prefix": prefix,
                    "number": number,
                    "allocated_at": datetime.now(timezone.utc),
                    "migration_source": "delete-tombstone",
                }
            },
            upsert=True,
            session=session,
        )
        self.db.identifier_counters.update_one(
            {"_id": prefix},
            {"$max": {"next_number": number + 1}},
            session=session,
        )
        current = self.db.identifier_counters.find_one(
            {"_id": prefix}, session=session
        )
        self._project_claim(prefix, number, int(current["next_number"]), session)


class ResourceRepository:
    """Create BIN/SKU/BAT resources with one idempotent transaction."""

    def __init__(self, database):
        self.db = database
        self.identifiers = PermanentIdentifierAllocator(database)
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.db.resource_commands.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="resource_command_idempotency_key",
        )

    def _run_transaction(self, callback: Callable) -> Any:
        with self.db.client.start_session() as session:
            return session.with_transaction(
                callback,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )

    @staticmethod
    def _canonical_command(
        prefix: str,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        if prefix == "BIN":
            return {
                "id": command.get("id"),
                "props": command.get("props", {}),
            }
        if prefix == "SKU":
            return {
                "id": command.get("id"),
                "owned_codes": command.get("owned_codes", []),
                "associated_codes": command.get("associated_codes", []),
                "name": command.get("name"),
                "props": command.get("props", {}),
            }
        if prefix == "BAT":
            return {
                "id": command.get("id"),
                "sku_id": command.get("sku_id"),
                "name": command.get("name"),
                "owned_codes": command.get("owned_codes", []),
                "associated_codes": command.get("associated_codes", []),
                "props": command.get("props", {}),
            }
        raise ValueError(f"unsupported resource prefix: {prefix}")

    def _existing_request(
        self,
        *,
        command_kind: str,
        idempotency_key: str,
        request_fingerprint: str,
        session,
    ) -> ResourceCreationResult | None:
        existing = self.db.resource_commands.find_one(
            {"idempotency_key": idempotency_key}, session=session
        )
        if existing is None:
            return None
        if (
            existing.get("kind") != command_kind
            or existing.get("request_fingerprint") != request_fingerprint
        ):
            raise ResourceIdempotencyConflict(idempotency_key)
        return ResourceCreationResult(existing["result"], replayed=True)

    def _reserve_reference(
        self,
        prefix: str,
        identifier: str,
        session,
    ) -> dict[str, Any] | None:
        collection = self.db[RESOURCE_COLLECTIONS[prefix]]
        token = uuid4().hex
        existing = collection.find_one_and_update(
            {"_id": identifier},
            {"$set": {"_resource_write_lock": token}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        if existing is not None:
            collection.update_one(
                {"_id": identifier, "_resource_write_lock": token},
                {"$unset": {"_resource_write_lock": ""}},
                session=session,
            )
        return existing

    @staticmethod
    def _document(prefix: str, state: dict[str, Any]) -> dict[str, Any]:
        if prefix == "BIN":
            return Bin(
                id=state["id"],
                props=state["props"],
            ).to_mongodb_doc()
        if prefix == "SKU":
            return Sku.from_json(state).to_mongodb_doc()
        if prefix == "BAT":
            document = Batch.from_json(state).to_mongodb_doc()
            # ``Props`` is an old fixed-field model that serializes absent
            # optional fields as null.  Creation state uses the cleaner JSON
            # shape, so retain only the properties the command actually
            # supplied while still using the model's BSON conversion for
            # currency values.
            document["props"] = {
                key: document["props"][key]
                for key in state["props"]
            }
            return document
        raise ValueError(f"unsupported resource prefix: {prefix}")

    def _insert_resource(
        self,
        prefix: str,
        state: dict[str, Any],
        actor: dict[str, str] | None,
        session,
    ) -> None:
        if prefix == "BAT" and state["sku_id"] is not None:
            if self._reserve_reference("SKU", state["sku_id"], session) is None:
                raise MissingResourceReference("SKU", state["sku_id"])
        self.db[RESOURCE_COLLECTIONS[prefix]].insert_one(
            self._document(prefix, state),
            session=session,
        )

    def _insert_receipt(
        self,
        *,
        command_kind: str,
        idempotency_key: str,
        request_fingerprint: str,
        state: dict[str, Any],
        actor: dict[str, str] | None,
        session,
    ) -> None:
        self.db.resource_commands.insert_one(
            {
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "kind": command_kind,
                "result": state,
                "actor": actor,
                "created_at": datetime.now(timezone.utc),
            },
            session=session,
        )

    def _recover_racing_request(
        self,
        *,
        command_kind: str,
        idempotency_key: str,
        request_fingerprint: str,
        original_error: DuplicateKeyError,
    ) -> ResourceCreationResult:
        existing = self.db.resource_commands.find_one(
            {"idempotency_key": idempotency_key}
        )
        if existing is None:
            raise ResourceIdentifierAlreadyUsed() from original_error
        if (
            existing.get("kind") != command_kind
            or existing.get("request_fingerprint") != request_fingerprint
        ):
            raise ResourceIdempotencyConflict(idempotency_key) from original_error
        return ResourceCreationResult(existing["result"], replayed=True)

    def create(
        self,
        prefix: str,
        command: dict[str, Any],
        *,
        idempotency_key: str,
        actor: dict[str, str] | None = None,
    ) -> ResourceCreationResult:
        command_kind = RESOURCE_COMMAND_KINDS[prefix]
        canonical_command = self._canonical_command(prefix, command)
        request_fingerprint = _fingerprint({"actor": actor, "command": canonical_command})

        def write(session):
            existing = self._existing_request(
                command_kind=command_kind,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                session=session,
            )
            if existing is not None:
                return existing

            identifier = self.identifiers.allocate(
                prefix,
                session,
                requested_id=canonical_command["id"],
            )
            state = {**canonical_command, "id": identifier}
            self._insert_resource(prefix, state, actor, session)
            self._insert_receipt(
                command_kind=command_kind,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                state=state,
                actor=actor,
                session=session,
            )
            return ResourceCreationResult(state, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            return self._recover_racing_request(
                command_kind=command_kind,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                original_error=error,
            )

    def next_available_id(self, prefix: str) -> str:
        return self._run_transaction(
            lambda session: self.identifiers.next_available_id(prefix, session)
        )

    def preserve_identifier(
        self,
        prefix: str,
        identifier: str,
        session,
    ) -> None:
        self.identifiers.preserve(prefix, identifier, session)
