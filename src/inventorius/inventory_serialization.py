"""Shared transaction-local serialization points for inventory references."""

from __future__ import annotations

from uuid import uuid4

from pymongo import ReturnDocument


def reserve_inventory_resource(collection, resource_id: str, session):
    """Keep one physical inventory resource stable through transaction commit.

    Inventory commands and audit observations deliberately write and remove
    the same internal marker. MongoDB therefore serializes their transactions
    on the named resource document without leaving application-visible state.
    """
    token = uuid4().hex
    existing = collection.find_one_and_update(
        {"_id": resource_id},
        {"$set": {"_ledger_write_lock": token}},
        return_document=ReturnDocument.AFTER,
        session=session,
    )
    if existing is not None:
        collection.update_one(
            {"_id": resource_id, "_ledger_write_lock": token},
            {"$unset": {"_ledger_write_lock": ""}},
            session=session,
        )
    return existing
