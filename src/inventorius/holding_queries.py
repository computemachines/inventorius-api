"""Read adapters that bridge legacy resource endpoints to ledger holdings."""

from decimal import Decimal

from bson.decimal128 import Decimal128

from inventorius.db import db


# The old endpoint shape has no unit or packaging columns.  It can truthfully
# bridge the first clean-break slice (unpackaged whole items), but must not
# collapse unlike holding keys into one misleading number.
_LEGACY_VISIBLE_HOLDING = {
    "unit": "each",
    "packaging_configuration_id": None,
}


def _decimal(value):
    return value.to_decimal() if isinstance(value, Decimal128) else Decimal(str(value))


def _quantity(value):
    decimal = _decimal(value)
    return int(decimal) if decimal == decimal.to_integral_value() else str(decimal)


def _add(locations, location_id, item_id, quantity):
    location = locations.setdefault(location_id, {})
    total = _decimal(location.get(item_id, 0)) + _decimal(quantity)
    location[item_id] = _quantity(total)


def locations_for_batch(batch_id):
    """Return legacy contents plus positive projected holdings for one batch."""
    locations = {}
    for bin_document in db.bin.find({f"contents.{batch_id}": {"$exists": True}}):
        _add(locations, bin_document["_id"], batch_id, bin_document["contents"][batch_id])
    for holding in db.inventory_holdings.find({
        "batch_id": batch_id,
        "quantity": {"$gt": Decimal128("0")},
        **_LEGACY_VISIBLE_HOLDING,
    }):
        _add(locations, holding["location_id"], batch_id, _quantity(holding["quantity"]))
    return locations


def locations_for_sku(sku_id):
    """Return legacy direct-SKU locations plus holdings of its linked batches."""
    locations = {}
    for bin_document in db.bin.find({f"contents.{sku_id}": {"$exists": True}}):
        _add(locations, bin_document["_id"], sku_id, bin_document["contents"][sku_id])

    batch_ids = [document["_id"] for document in db.batch.find(
        {"sku_id": sku_id}, {"_id": 1}
    )]
    if batch_ids:
        for holding in db.inventory_holdings.find({
            "batch_id": {"$in": batch_ids},
            "quantity": {"$gt": Decimal128("0")},
            **_LEGACY_VISIBLE_HOLDING,
        }):
            _add(locations, holding["location_id"], sku_id, _quantity(holding["quantity"]))
    return locations


def contents_for_bin(bin_document):
    """Overlay positive ledger holdings on the legacy persisted contents map."""
    contents = dict(bin_document.get("contents", {}))
    for holding in db.inventory_holdings.find({
        "location_id": bin_document["_id"],
        "quantity": {"$gt": Decimal128("0")},
        **_LEGACY_VISIBLE_HOLDING,
    }):
        batch_id = holding["batch_id"]
        contents[batch_id] = contents.get(batch_id, 0) + _quantity(holding["quantity"])
    return contents


def identity_has_ledger_history(item_id):
    """Whether a legacy SKU/BAT contents mutation would split ledger state.

    A zero balance is still ledger history: a released batch has an immutable
    receive/release trail even when its current projection is empty.  SKU
    operations are represented through their batches, while BAT operations
    name the batch directly.
    """
    if item_id.startswith("BAT"):
        batch_ids = [item_id]
    elif item_id.startswith("SKU"):
        batch_ids = [document["_id"] for document in db.batch.find(
            {"sku_id": item_id}, {"_id": 1}
        )]
    else:
        return False

    if not batch_ids:
        return False

    batch_filter = {"$in": batch_ids}
    return any((
        db.inventory_operations.find_one(
            {"legs.batch_id": batch_filter}, {"_id": 1}
        ),
        db.inventory_holdings.find_one(
            {"batch_id": batch_filter}, {"_id": 1}
        ),
        # Observations are emitted by ledger intake too.  This guards against
        # partial historical data without treating the observation itself as
        # an ownership assertion.
        db.inventory_code_observations.find_one(
            {"batch_id": batch_filter}, {"_id": 1}
        ),
    ))
