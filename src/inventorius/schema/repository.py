"""Immutable publication history for dynamic schemas.

The ``schema`` collection remains a small current-head projection so existing
read paths stay cheap.  Published definitions live in ``schema_revision`` as
separate immutable documents addressed by logical schema name and revision.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


COMPATIBILITY_UNSPECIFIED = "unspecified"
BOOTSTRAP_ACTOR = {
    "actor_id": "schema-bootstrap",
    "actor_type": "system",
}


class SchemaEditConflict(RuntimeError):
    """The schema head changed after a caller read it."""


@dataclass(frozen=True)
class SchemaHead:
    """One observed logical schema head and its compare-and-swap token."""

    name: str
    definition: dict[str, Any] | None
    head_revision: int | None
    active_revision: int | None
    exists: bool
    legacy: bool
    _document: dict[str, Any] | None

    @property
    def active(self) -> bool:
        if not self.exists:
            return False
        if self.legacy:
            return True
        return (
            self.head_revision is not None
            and self.active_revision == self.head_revision
        )


@dataclass(frozen=True)
class SchemaPublication:
    """Outcome of publishing or reactivating a schema head."""

    changed: bool
    revision: int | None


def _legacy_definition(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in document.items()
        if key != "_id"
    }


def _revision_id(name: str, revision: int) -> dict[str, Any]:
    return {"schema_name": name, "revision": revision}


class SchemaRepository:
    """Read schema projections and publish immutable revisions with CAS."""

    def __init__(self, database: Any):
        self.db = database

    @staticmethod
    def _head_from_document(
        name: str,
        document: dict[str, Any] | None,
    ) -> SchemaHead:
        if document is None:
            return SchemaHead(
                name=name,
                definition=None,
                head_revision=None,
                active_revision=None,
                exists=False,
                legacy=False,
                _document=None,
            )

        if (
            isinstance(document.get("head_revision"), int)
            and isinstance(document.get("definition"), dict)
        ):
            return SchemaHead(
                name=name,
                definition=deepcopy(document["definition"]),
                head_revision=document["head_revision"],
                active_revision=document.get("active_revision"),
                exists=True,
                legacy=False,
                _document=deepcopy(document),
            )

        return SchemaHead(
            name=name,
            definition=_legacy_definition(document),
            head_revision=None,
            active_revision=None,
            exists=True,
            legacy=True,
            _document=deepcopy(document),
        )

    def head(self, name: str, *, session: Any = None) -> SchemaHead:
        document = self.db.schema.find_one({"_id": name}, session=session)
        return self._head_from_document(name, document)

    def definition(
        self,
        name: str,
        *,
        revision: int | None = None,
    ) -> dict[str, Any] | None:
        """Return the active projection or one exact published revision."""

        if revision is not None:
            document = self.db.schema_revision.find_one({
                "_id": _revision_id(name, revision),
            })
            if document is None:
                return None
            return deepcopy(document["definition"])

        head = self.head(name)
        if not head.active:
            return None
        return deepcopy(head.definition)

    @staticmethod
    def _same_observation(expected: SchemaHead, observed: SchemaHead) -> bool:
        if (
            expected.exists != observed.exists
            or expected.legacy != observed.legacy
        ):
            return False
        if not expected.exists:
            return True
        if expected.legacy:
            return expected._document == observed._document
        return (
            expected.head_revision == observed.head_revision
            and expected.active_revision == observed.active_revision
            and expected.definition == observed.definition
        )

    @staticmethod
    def _revision_document(
        *,
        name: str,
        revision: int,
        parent_revision: int | None,
        definition: dict[str, Any],
        actor: dict[str, str] | None,
        published_at: datetime | None,
    ) -> dict[str, Any]:
        return {
            "_id": _revision_id(name, revision),
            "schema_name": name,
            "revision": revision,
            "parent_revision": parent_revision,
            "definition": deepcopy(definition),
            "actor": deepcopy(actor),
            "published_at": published_at,
            "compatibility": COMPATIBILITY_UNSPECIFIED,
        }

    @staticmethod
    def _head_document(
        name: str,
        definition: dict[str, Any],
        revision: int,
        *,
        active: bool,
    ) -> dict[str, Any]:
        return {
            "_id": name,
            "head_revision": revision,
            "active_revision": revision if active else None,
            "definition": deepcopy(definition),
        }

    def _replace_observed_head(
        self,
        observed: SchemaHead,
        replacement: dict[str, Any],
        *,
        session: Any,
    ) -> None:
        if not observed.exists:
            self.db.schema.insert_one(replacement, session=session)
            return

        if observed.legacy:
            selector = observed._document
        else:
            selector = {
                "_id": observed.name,
                "head_revision": observed.head_revision,
                "active_revision": observed.active_revision,
                "definition": observed.definition,
            }
        result = self.db.schema.replace_one(
            selector,
            replacement,
            session=session,
        )
        if result.modified_count != 1:
            raise SchemaEditConflict(observed.name)

    def publish(
        self,
        name: str,
        definition: dict[str, Any],
        *,
        actor: dict[str, str] | None,
        expected: SchemaHead | None = None,
    ) -> SchemaPublication:
        """Publish changed content, preserving every prior definition.

        Legacy flat documents remain readable.  Their first changed publication
        records the exact pre-revision document as revision 1 with unknown
        publication metadata, then records the new definition as revision 2.
        """

        proposed = deepcopy(definition)

        def transaction(session):
            observed = self.head(name, session=session)
            if expected is not None and not self._same_observation(
                expected, observed
            ):
                raise SchemaEditConflict(name)

            if observed.exists and observed.definition == proposed:
                if observed.active:
                    return SchemaPublication(
                        changed=False,
                        revision=observed.head_revision,
                    )
                # A PUT is the existing activation seam.  Restoring an
                # unchanged, revisioned definition does not invent a revision.
                replacement = self._head_document(
                    name,
                    proposed,
                    observed.head_revision,
                    active=True,
                )
                self._replace_observed_head(
                    observed,
                    replacement,
                    session=session,
                )
                return SchemaPublication(
                    changed=True,
                    revision=observed.head_revision,
                )

            timestamp = datetime.now(timezone.utc)
            if not observed.exists:
                revision = 1
                self.db.schema_revision.insert_one(
                    self._revision_document(
                        name=name,
                        revision=revision,
                        parent_revision=None,
                        definition=proposed,
                        actor=actor,
                        published_at=timestamp,
                    ),
                    session=session,
                )
            elif observed.legacy:
                baseline_revision = 1
                self.db.schema_revision.insert_one(
                    self._revision_document(
                        name=name,
                        revision=baseline_revision,
                        parent_revision=None,
                        definition=observed.definition,
                        actor=None,
                        published_at=None,
                    ),
                    session=session,
                )
                revision = 2
                self.db.schema_revision.insert_one(
                    self._revision_document(
                        name=name,
                        revision=revision,
                        parent_revision=baseline_revision,
                        definition=proposed,
                        actor=actor,
                        published_at=timestamp,
                    ),
                    session=session,
                )
            else:
                revision = observed.head_revision + 1
                self.db.schema_revision.insert_one(
                    self._revision_document(
                        name=name,
                        revision=revision,
                        parent_revision=observed.head_revision,
                        definition=proposed,
                        actor=actor,
                        published_at=timestamp,
                    ),
                    session=session,
                )

            self._replace_observed_head(
                observed,
                self._head_document(name, proposed, revision, active=True),
                session=session,
            )
            return SchemaPublication(changed=True, revision=revision)

        try:
            with self.db.client.start_session() as session:
                return session.with_transaction(
                    transaction,
                    read_concern=ReadConcern("snapshot"),
                    write_concern=WriteConcern("majority"),
                )
        except DuplicateKeyError as error:
            raise SchemaEditConflict(name) from error

    def deactivate(
        self,
        name: str,
        *,
        expected: SchemaHead | None = None,
    ) -> bool:
        """Deactivate the head without removing any published definition."""

        def transaction(session):
            observed = self.head(name, session=session)
            if expected is not None and not self._same_observation(
                expected, observed
            ):
                raise SchemaEditConflict(name)
            if not observed.active:
                return False

            if observed.legacy:
                revision = 1
                self.db.schema_revision.insert_one(
                    self._revision_document(
                        name=name,
                        revision=revision,
                        parent_revision=None,
                        definition=observed.definition,
                        actor=None,
                        published_at=None,
                    ),
                    session=session,
                )
            else:
                revision = observed.head_revision

            self._replace_observed_head(
                observed,
                self._head_document(
                    name,
                    observed.definition,
                    revision,
                    active=False,
                ),
                session=session,
            )
            return True

        try:
            with self.db.client.start_session() as session:
                return session.with_transaction(
                    transaction,
                    read_concern=ReadConcern("snapshot"),
                    write_concern=WriteConcern("majority"),
                )
        except DuplicateKeyError as error:
            raise SchemaEditConflict(name) from error

    def active_names(self) -> list[str]:
        names = []
        for document in self.db.schema.find({}):
            head = self._head_from_document(document["_id"], document)
            if head.active:
                names.append(head.name)
        return names
