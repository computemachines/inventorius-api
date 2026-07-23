"""Compatibility facade for the shared resource identity repository.

New code should use :mod:`inventorius.resource_repository` directly.  Keeping
this narrow wrapper avoids making older callers and focused Bin tests aware of
the migration all at once.
"""

from inventorius.resource_repository import (
    ResourceCreationResult as BinCreationResult,
    ResourceIdempotencyConflict as BinIdempotencyConflict,
    ResourceIdentifierAlreadyUsed as BinIdentifierAlreadyUsed,
    ResourceRepository,
)


class BinRepository:
    """Legacy Bin-shaped API backed by the shared BIN/SKU/BAT repository."""

    prefix = "BIN"
    command_kind = "create-bin"

    def __init__(self, database):
        self.repository = ResourceRepository(database)

    @property
    def db(self):
        return self.repository.db

    def create(self, command, *, idempotency_key):
        return self.repository.create(
            self.prefix,
            command,
            idempotency_key=idempotency_key,
        )

    def next_available_id(self):
        return self.repository.next_available_id(self.prefix)

    def preserve_identifier(self, identifier, session):
        self.repository.preserve_identifier(self.prefix, identifier, session)
