"""Durable actor receipts for legacy mutable resources.

The inventory ledger already has its own fact model.  Catalog, file, and
schema records predate that model, so their mutation receipts live separately
without changing the shape consumed by their older serializers.
"""

from datetime import datetime, timezone
from uuid import uuid4


def record_mutation(database, *, kind: str, target: str, actor: dict[str, str] | None):
    """Append the authenticated actor for one successful mutable-resource call."""

    database.mutation_receipts.insert_one({
        "_id": uuid4().hex,
        "receipt_type": "inventorius.mutable-resource",
        "envelope_version": 1,
        "kind": kind,
        "target": target,
        "actor": actor,
        "recorded_at": datetime.now(timezone.utc),
    })
