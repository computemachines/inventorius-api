"""Transactional persistence for physical Bin identities.

Creating a Bin is a resource command, not an inventory movement.  Its durable
idempotency receipt therefore lives in ``resource_commands`` rather than the
append-only inventory operation ledger.  Identifier claims are retained after
the Bin document is deleted so a physical label can never acquire a new
meaning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable

from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from inventorius.data_models import Bin
from inventorius.util import IdentifierSpaceExhausted, MAX_IDENTIFIER_SUFFIX


class BinIdempotencyConflict(ValueError):
    """An idempotency key was reused for a different Bin command."""


class BinIdentifierAlreadyUsed(ValueError):
    """A Bin identifier is live or has existed at any time in the past."""


@dataclass(frozen=True)
class BinCreationResult:
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


def _suffix(identifier: str) -> int:
    return int(identifier[3:])


def _canonical_bin_id(number: int) -> str:
    return f"BIN{number:06d}"


class BinRepository:
    """Allocate and create Bins in one idempotent Mongo transaction."""

    prefix = "BIN"
    command_kind = "create-bin"

    def __init__(self, database):
        self.db = database
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.db.resource_commands.create_index(
            [("idempotency_key", ASCENDING)],
            unique=True,
            name="resource_command_idempotency_key",
        )
        self.db.resource_identifiers.create_index(
            [("prefix", ASCENDING), ("number", ASCENDING)],
            unique=True,
            name="resource_identifier_number",
        )

    def _run_transaction(self, callback: Callable) -> Any:
        with self.db.client.start_session() as session:
            return session.with_transaction(
                callback,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
            )

    @staticmethod
    def _valid_suffix(identifier: object) -> int | None:
        match = re.fullmatch(r"BIN(\d{1,6})", str(identifier))
        if match is None:
            return None
        number = int(match.group(1))
        if number > MAX_IDENTIFIER_SUFFIX:
            return None
        return number

    def _legacy_state(self, session) -> tuple[set[int], int, int]:
        """Return known used numbers, next floor, and conservative old floor."""
        admin = self.db.admin.find_one({"_id": self.prefix}, session=session)
        live_numbers = {
            number
            for document in self.db.bin.find({}, {"_id": 1}, session=session)
            if (number := self._valid_suffix(document.get("_id"))) is not None
        }
        claimed_numbers = {
            int(document["number"])
            for document in self.db.resource_identifiers.find(
                {"prefix": self.prefix}, {"number": 1}, session=session
            )
        }

        admin_used: set[int] = set()
        legacy_reserved_below = 0
        admin_next = 1
        if admin is not None:
            for value in admin.get("used", []):
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= number <= MAX_IDENTIFIER_SUFFIX:
                    admin_used.add(number)

            next_value = admin.get("next")
            next_number = self._valid_suffix(next_value) if next_value else None
            if admin.get("exhausted"):
                admin_next = MAX_IDENTIFIER_SUFFIX + 1
            elif next_number is not None:
                admin_next = next_number

            # Very old admin documents had only a monotonic ``next`` field.
            # A missing ``used`` list means deleted lower IDs are unknowable,
            # so reserve the old range rather than risk giving an old label a
            # new meaning.
            if "used" not in admin:
                legacy_reserved_below = admin_next

        known_used = admin_used | live_numbers | claimed_numbers
        next_number = max(
            admin_next,
            (max(known_used) + 1) if known_used else 1,
        )
        return known_used, next_number, legacy_reserved_below

    def _ensure_counter(self, session) -> dict[str, Any]:
        counter = self.db.identifier_counters.find_one(
            {"_id": self.prefix}, session=session
        )
        if counter is not None:
            return counter

        known_used, next_number, legacy_reserved_below = self._legacy_state(session)
        self.db.identifier_counters.update_one(
            {"_id": self.prefix},
            {"$setOnInsert": {
                "next_number": next_number,
                "legacy_reserved_below": legacy_reserved_below,
            }},
            upsert=True,
            session=session,
        )

        # Keep the transitional admin projection coherent for old readers.
        admin_state = {
            "next": (
                None
                if next_number > MAX_IDENTIFIER_SUFFIX
                else _canonical_bin_id(next_number)
            ),
            "exhausted": next_number > MAX_IDENTIFIER_SUFFIX,
        }
        self.db.admin.update_one(
            {"_id": self.prefix},
            {
                "$setOnInsert": {"used": []},
                "$set": admin_state,
            },
            upsert=True,
            session=session,
        )
        if known_used:
            self.db.admin.update_one(
                {"_id": self.prefix},
                {"$addToSet": {"used": {"$each": sorted(known_used)}}},
                session=session,
            )
        return self.db.identifier_counters.find_one(
            {"_id": self.prefix}, session=session
        )

    def _project_legacy_admin(self, number: int, next_number: int, session) -> None:
        self.db.admin.update_one(
            {"_id": self.prefix},
            {
                "$addToSet": {"used": number},
                "$set": {
                    "next": (
                        None
                        if next_number > MAX_IDENTIFIER_SUFFIX
                        else _canonical_bin_id(next_number)
                    ),
                    "exhausted": next_number > MAX_IDENTIFIER_SUFFIX,
                },
            },
            upsert=True,
            session=session,
        )

    def _is_known_used(self, identifier: str, number: int, counter, session) -> bool:
        if number < int(counter.get("legacy_reserved_below", 0)):
            return True
        if self.db.resource_identifiers.find_one(
            {"_id": identifier}, {"_id": 1}, session=session
        ) is not None:
            return True
        if self.db.bin.find_one(
            {"_id": identifier}, {"_id": 1}, session=session
        ) is not None:
            return True
        return self.db.admin.find_one(
            {"_id": self.prefix, "used": number}, {"_id": 1}, session=session
        ) is not None

    def _claim_identifier(self, identifier: str, number: int, session) -> None:
        self.db.resource_identifiers.insert_one(
            {
                "_id": identifier,
                "prefix": self.prefix,
                "number": number,
                "allocated_at": datetime.now(timezone.utc),
            },
            session=session,
        )

    def _allocate_identifier(self, requested_id: str | None, session) -> str:
        counter = self._ensure_counter(session)
        if requested_id is not None:
            number = _suffix(requested_id)
            if self._is_known_used(requested_id, number, counter, session):
                raise BinIdentifierAlreadyUsed(requested_id)
            self._claim_identifier(requested_id, number, session)
            self.db.identifier_counters.update_one(
                {"_id": self.prefix},
                {"$max": {"next_number": number + 1}},
                session=session,
            )
            current = self.db.identifier_counters.find_one(
                {"_id": self.prefix}, session=session
            )
            self._project_legacy_admin(number, current["next_number"], session)
            return requested_id

        before = self.db.identifier_counters.find_one_and_update(
            {
                "_id": self.prefix,
                "next_number": {"$lte": MAX_IDENTIFIER_SUFFIX},
            },
            {"$inc": {"next_number": 1}},
            return_document=ReturnDocument.BEFORE,
            session=session,
        )
        if before is None:
            raise IdentifierSpaceExhausted(self.prefix)
        number = int(before["next_number"])
        identifier = _canonical_bin_id(number)
        self._claim_identifier(identifier, number, session)
        self._project_legacy_admin(number, number + 1, session)
        return identifier

    def _existing_request(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        session,
    ) -> BinCreationResult | None:
        existing = self.db.resource_commands.find_one(
            {"idempotency_key": idempotency_key}, session=session
        )
        if existing is None:
            return None
        if (
            existing.get("kind") != self.command_kind
            or existing["request_fingerprint"] != request_fingerprint
        ):
            raise BinIdempotencyConflict(idempotency_key)
        return BinCreationResult(existing["result"], replayed=True)

    def _insert_bin(self, state: dict[str, Any], session) -> None:
        data_bin = Bin(id=state["id"], props=state["props"])
        self.db.bin.insert_one(data_bin.to_mongodb_doc(), session=session)

    def _insert_receipt(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        state: dict[str, Any],
        session,
    ) -> None:
        self.db.resource_commands.insert_one(
            {
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "kind": self.command_kind,
                "result": state,
                "created_at": datetime.now(timezone.utc),
            },
            session=session,
        )

    def _recover_racing_request(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        original_error: DuplicateKeyError,
    ) -> BinCreationResult:
        existing = self.db.resource_commands.find_one(
            {"idempotency_key": idempotency_key}
        )
        if existing is None:
            raise BinIdentifierAlreadyUsed() from original_error
        if (
            existing.get("kind") != self.command_kind
            or existing["request_fingerprint"] != request_fingerprint
        ):
            raise BinIdempotencyConflict(idempotency_key) from original_error
        return BinCreationResult(existing["result"], replayed=True)

    def create(
        self,
        command: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> BinCreationResult:
        """Create one Bin, replaying the exact state after a lost response."""
        canonical_command = {
            "id": command.get("id"),
            "props": command.get("props", {}),
        }
        request_fingerprint = _fingerprint(canonical_command)

        def write(session):
            existing = self._existing_request(
                idempotency_key, request_fingerprint, session
            )
            if existing is not None:
                return existing

            identifier = self._allocate_identifier(
                canonical_command["id"], session
            )
            state = {
                "id": identifier,
                "props": canonical_command["props"],
            }
            self._insert_bin(state, session)
            self._insert_receipt(
                idempotency_key, request_fingerprint, state, session
            )
            return BinCreationResult(state, replayed=False)

        try:
            return self._run_transaction(write)
        except DuplicateKeyError as error:
            return self._recover_racing_request(
                idempotency_key, request_fingerprint, error
            )

    def next_available_id(self) -> str:
        """Return a non-reserving preview for legacy/read-only clients."""
        def read(session):
            counter = self._ensure_counter(session)
            number = int(counter["next_number"])
            if number > MAX_IDENTIFIER_SUFFIX:
                raise IdentifierSpaceExhausted(self.prefix)
            return _canonical_bin_id(number)

        return self._run_transaction(read)

    def preserve_identifier(self, identifier: str, session) -> None:
        """Tombstone a pre-migration Bin before its document is deleted."""
        counter = self._ensure_counter(session)
        number = _suffix(identifier)
        self.db.resource_identifiers.update_one(
            {"_id": identifier},
            {"$setOnInsert": {
                "prefix": self.prefix,
                "number": number,
                "allocated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
            session=session,
        )
        self.db.identifier_counters.update_one(
            {"_id": self.prefix},
            {"$max": {"next_number": number + 1}},
            session=session,
        )
        current = self.db.identifier_counters.find_one(
            {"_id": self.prefix}, session=session
        )
        self._project_legacy_admin(number, current["next_number"], session)
