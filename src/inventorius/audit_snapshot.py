"""Read-only inventory snapshots for a physical audit.

This adapter deliberately exposes the canonical holding projection without
trying to reconcile it with ``bin.contents``.  Legacy contents and holding
shapes that the first audit UI cannot safely count are reported as blockers
instead of being silently interpreted.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from bson.decimal128 import Decimal128


LEGACY_CONTENTS_BLOCKER = "legacy-bin-contents"
UNSUPPORTED_HOLDINGS_BLOCKER = "unsupported-holding-shapes"


def _decimal(value: Decimal128 | Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_quantity(quantity: Decimal) -> int | str:
    if quantity == quantity.to_integral_value():
        return int(quantity)
    return format(quantity, "f")


def _token_quantity(quantity: Decimal) -> str:
    """Return one value-stable representation for snapshot hashing."""
    if quantity == quantity.to_integral_value():
        return str(int(quantity))
    return format(quantity.normalize(), "f")


def _holding_sort_key(holding: dict[str, Any]) -> tuple[str, str, int, str]:
    packaging = holding.get("packaging_configuration_id")
    return (
        holding["batch_id"],
        holding["unit"],
        packaging is not None,
        packaging or "",
    )


def _is_supported(
    *,
    quantity: Decimal,
    unit: str,
    packaging_configuration_id: str | None,
) -> bool:
    return (
        unit == "each"
        and packaging_configuration_id is None
        and quantity == quantity.to_integral_value()
    )


def _snapshot_token(location_id: str, holdings: list[dict[str, Any]]) -> str:
    identities = [
        [
            holding["batch_id"],
            location_id,
            holding["unit"],
            holding.get("packaging_configuration_id"),
            _token_quantity(holding["_quantity"]),
        ]
        for holding in holdings
    ]
    encoded = json.dumps(
        identities,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def read_audit_snapshot(
    database,
    location_id: str,
    *,
    session=None,
) -> dict[str, Any] | None:
    """Return one immutable view of canonical holdings at ``location_id``.

    Enrichment is intentionally bounded: one Batch query and, when needed, one
    SKU query cover every holding in the snapshot.
    """
    bin_document = database.bin.find_one(
        {"_id": location_id},
        {"contents": 1},
        session=session,
    )
    if bin_document is None:
        return None

    holding_documents = list(database.inventory_holdings.find(
        {
            "location_id": location_id,
            "quantity": {"$gt": Decimal128("0")},
        },
        {
            "_id": 0,
            "batch_id": 1,
            "location_id": 1,
            "quantity": 1,
            "unit": 1,
            "packaging_configuration_id": 1,
        },
        session=session,
    ))
    holding_documents.sort(key=_holding_sort_key)

    batch_ids = sorted({holding["batch_id"] for holding in holding_documents})
    batches = {
        document["_id"]: document
        for document in database.batch.find(
            {"_id": {"$in": batch_ids}},
            {"_id": 1, "name": 1, "sku_id": 1},
            session=session,
        )
    } if batch_ids else {}

    sku_ids = sorted({
        document["sku_id"]
        for document in batches.values()
        if document.get("sku_id")
    })
    skus = {
        document["_id"]: document
        for document in database.sku.find(
            {"_id": {"$in": sku_ids}},
            {"_id": 1, "name": 1},
            session=session,
        )
    } if sku_ids else {}

    holdings = []
    unsupported_count = 0
    for document in holding_documents:
        quantity = _decimal(document["quantity"])
        batch = batches.get(document["batch_id"], {})
        sku_id = batch.get("sku_id")
        sku = skus.get(sku_id, {}) if sku_id else {}
        packaging_configuration_id = document.get(
            "packaging_configuration_id"
        )
        supported = _is_supported(
            quantity=quantity,
            unit=document["unit"],
            packaging_configuration_id=packaging_configuration_id,
        )
        if not supported:
            unsupported_count += 1
        holdings.append({
            "batch_id": document["batch_id"],
            "sku_id": sku_id,
            "batch_name": batch.get("name"),
            "sku_name": sku.get("name"),
            "quantity": _json_quantity(quantity),
            "unit": document["unit"],
            "packaging_configuration_id": packaging_configuration_id,
            "supported": supported,
            "_quantity": quantity,
        })

    token = _snapshot_token(location_id, holdings)
    for holding in holdings:
        del holding["_quantity"]

    blockers = []
    legacy_contents = bin_document.get("contents") or {}
    if legacy_contents:
        blockers.append({
            "type": LEGACY_CONTENTS_BLOCKER,
            "entry_count": len(legacy_contents),
        })
    if unsupported_count:
        blockers.append({
            "type": UNSUPPORTED_HOLDINGS_BLOCKER,
            "holding_count": unsupported_count,
        })

    return {
        "location_id": location_id,
        "snapshot_token": token,
        "holdings": holdings,
        "blockers": blockers,
    }
