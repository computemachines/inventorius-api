from decimal import Decimal
import json
import re

from bson.decimal128 import Decimal128
from flask import Blueprint, request, Response, url_for

from inventorius.data_models import Bin, Sku, Batch, DataModelJSONEncoder as Encoder
from inventorius.db import db
from inventorius.auth import public_unsafe
from inventorius.resource_repository import ResourceRepository
from inventorius.util import (
    IdentifierSpaceExhausted,
    getIntArgs,
    no_cache,
)
import inventorius.util_error_responses as problem

inventorius = Blueprint("inventorius", __name__)


def _search_reason(*, kind, value, scope, relationship=None):
    """Return the small, stable explanation attached to a search hit.

    Search results themselves retain their historic resource shape.  The
    explanation deliberately lives in the additive ``state.details`` sidecar,
    so old clients can continue to deserialize rows as Bin, Sku, or Batch.
    """
    reason = {
        "kind": kind,
        "value": value,
        "scope": scope,
    }
    if relationship is not None:
        reason["relationship"] = relationship
    return reason


def _search_scope(model):
    return {
        Bin: "bin",
        Sku: "sku",
        Batch: "batch",
    }[model]


def _json_holding_quantity(value):
    """Keep a holding quantity exact without pretending every value is an int."""
    if isinstance(value, Decimal128):
        value = value.to_decimal()
    else:
        value = Decimal(str(value))
    return int(value) if value == value.to_integral_value() else str(value)


def _search_locations(models):
    """Return raw positive canonical holdings for each returned resource.

    A SKU can cover several Batches, and a Batch can have several unit or
    packaging shapes in one location.  Keeping every projection row separate
    is intentional: aggregating those rows would create an invented quantity.
    Bins are locations, not inventory identities, so they have no item
    holdings in this result-side contract.
    """
    batch_ids_by_resource = {}
    all_batch_ids = set()
    sku_ids = [model.id for model in models if isinstance(model, Sku)]
    batches_by_sku = {}
    if sku_ids:
        for document in db.batch.find(
            {"sku_id": {"$in": sku_ids}}, {"_id": 1, "sku_id": 1}
        ):
            batches_by_sku.setdefault(document["sku_id"], set()).add(
                document["_id"]
            )

    for model in models:
        if isinstance(model, Batch):
            batch_ids = {model.id}
        elif isinstance(model, Sku):
            batch_ids = batches_by_sku.get(model.id, set())
        else:
            batch_ids = set()
        batch_ids_by_resource[model.id] = batch_ids
        all_batch_ids.update(batch_ids)

    holdings_by_batch = {}
    if all_batch_ids:
        for holding in db.inventory_holdings.find({
            "batch_id": {"$in": sorted(all_batch_ids)},
            "quantity": {"$gt": Decimal128("0")},
        }):
            batch_id = holding.get("batch_id")
            if not isinstance(batch_id, str):
                continue
            holdings_by_batch.setdefault(batch_id, []).append({
                "location_id": holding.get("location_id"),
                "batch_id": batch_id,
                "quantity": _json_holding_quantity(holding.get("quantity")),
                "unit": holding.get("unit"),
                "packaging_configuration_id": holding.get(
                    "packaging_configuration_id"
                ),
            })

    locations_by_resource = {}
    for model in models:
        locations = [
            location
            for batch_id in batch_ids_by_resource[model.id]
            for location in holdings_by_batch.get(batch_id, [])
        ]
        locations.sort(key=lambda location: (
            str(location["location_id"]),
            location["batch_id"],
            str(location["unit"]),
            str(location["packaging_configuration_id"]),
        ))
        locations_by_resource[model.id] = locations
    return locations_by_resource


def _search_response(*, hits, starting_from, limit):
    """Serialize historic rows plus additive, page-local search details."""
    paged_hits = hits[starting_from:(starting_from + limit)]
    paged_models = [hit["model"] for hit in paged_hits]
    locations = _search_locations(paged_models)
    details = {
        model.id: {
            "matched_by": hit["matched_by"],
            "locations": locations[model.id],
        }
        for hit in paged_hits
        for model in [hit["model"]]
    }
    return {
        "state": {
            "total_num_results": len(hits),
            "starting_from": starting_from,
            "limit": limit,
            "returned_num_results": len(paged_hits),
            "results": paged_models,
            "details": details,
        },
        "operations": [],
    }


@inventorius.route('/api/codes/<path:code>/usage', methods=['GET'])
@no_cache
def code_usage_get(code):
    used_by = []
    for collection, resource_type in ((db.sku, "sku"), (db.batch, "batch")):
        for relationship, field in (
            ("owned", "owned_codes"),
            ("associated", "associated_codes"),
        ):
            for document in collection.find({field: code}):
                used_by.append({
                    "type": resource_type,
                    "id": document["_id"],
                    "name": document.get("name"),
                    "relationship": relationship,
                })

    # This is deliberately a separate relationship from the legacy code
    # arrays: an observed external code is evidence about a batch, not a claim
    # that it is owned by or associated with that batch.
    for observation in db.inventory_code_observations.find({"code": code}):
        batch_document = db.batch.find_one({"_id": observation["batch_id"]})
        if batch_document is not None:
            used_by.append({
                "type": "batch",
                "id": batch_document["_id"],
                "name": batch_document.get("name"),
                "relationship": "observed",
            })

    return {"code": code, "usedBy": used_by}



@inventorius.route('/api/bin/<id>/contents/move', methods=['PUT'])
@public_unsafe
@no_cache
def move_bin_contents_put(id):
    # CUT-01 deliberately ends the mutable bin.contents accounting path. The
    # read adapters remain available, but all new movement is an immutable
    # ledger operation through /api/inventory-operations.
    return problem.operation_retired_response()


@inventorius.route('/api/next/sku', methods=['GET'])
def next_sku():
    try:
        next_id = ResourceRepository(db).next_available_id("SKU")
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    resp = Response()
    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_sku"),
        "state": next_id,
    })
    return resp

@inventorius.route('/api/next/batch', methods=['GET'])
def next_batch():
    try:
        next_id = ResourceRepository(db).next_available_id("BAT")
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    resp = Response()
    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_batch"),
        "state": next_id,
    })
    return resp


@inventorius.route('/api/next/bin', methods=['GET'])
def next_bin():
    try:
        next_id = ResourceRepository(db).next_available_id("BIN")
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    resp = Response()
    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_bin"),
        "state": next_id,
    })
    return resp



@inventorius.route('/api/bin/<bin_id>/contents', methods=["POST"])
@public_unsafe
@no_cache
def bin_contents_post(bin_id):
    # This route used to make the ledger and bin.contents disagree. It is
    # deliberately retained only as a clear migration error.
    return problem.operation_retired_response()


@inventorius.route('/api/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip()
    upper_query = query.upper()
    # Internal labels are deliberately tolerant of scanner/operator spacing.
    # Keep the raw query for external-code matching: a code containing a space
    # is still a distinct external code and must win over shorthand parsing.
    compact_upper_query = re.sub(r"\s+", "", upper_query)
    limit = max(1, min(getIntArgs(request.args, "limit", 20), 100))
    startingFrom = max(0, getIntArgs(request.args, "startingFrom", 0))
    resp = Response()

    hits = []
    hits_by_key = {}

    def add_result(model, reason):
        if model is None:
            return
        key = (type(model).__name__, model.id)
        hit = hits_by_key.get(key)
        if hit is None:
            hit = {"model": model, "matched_by": []}
            hits_by_key[key] = hit
            hits.append(hit)
        if reason not in hit["matched_by"]:
            hit["matched_by"].append(reason)

    if not query:
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps({'state': {
            "total_num_results": 0,
            "starting_from": startingFrom,
            "limit": limit,
            "returned_num_results": 0,
            "results": [],
            "details": {},
        }, "operations": []})
        return resp

    # An exact external code is stronger evidence than a coincidental text or
    # identifier match.  A scanner should return only the resources that
    # explicitly carry the code, even where the code is shared.
    exact_code_hits = []
    exact_code_hits_by_key = {}

    def add_exact_code_result(model, document, relationship):
        if document is None:
            return
        resource_key = (model.__name__, document["_id"])
        hit = exact_code_hits_by_key.get(resource_key)
        if hit is None:
            hit = {
                "model": model.from_mongodb_doc(document),
                "matched_by": [],
            }
            exact_code_hits_by_key[resource_key] = hit
            exact_code_hits.append(hit)
        reason = _search_reason(
            kind="exact-code",
            value=query,
            scope=_search_scope(model),
            relationship=relationship,
        )
        if reason not in hit["matched_by"]:
            hit["matched_by"].append(reason)

    for sku_document in db.sku.find({"$or": [
        {"owned_codes": query}, {"associated_codes": query},
    ]}):
        for relationship in ("owned", "associated"):
            if query in sku_document.get(f"{relationship}_codes", []):
                add_exact_code_result(Sku, sku_document, relationship)
    for batch_document in db.batch.find({"$or": [
        {"owned_codes": query}, {"associated_codes": query},
    ]}):
        for relationship in ("owned", "associated"):
            if query in batch_document.get(f"{relationship}_codes", []):
                add_exact_code_result(Batch, batch_document, relationship)
    for observation in db.inventory_code_observations.find({"code": query}):
        add_exact_code_result(
            Batch, db.batch.find_one({"_id": observation["batch_id"]}), "observed"
        )

    if exact_code_hits:
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps(
            _search_response(
                hits=exact_code_hits, starting_from=startingFrom, limit=limit
            ),
            cls=Encoder,
        )
        return resp

    # debug flags
    if upper_query == '!ALL':
        for document in db.sku.find():
            add_result(Sku.from_mongodb_doc(document), _search_reason(
                kind="debug", value=query, scope="sku"
            ))
        for document in db.batch.find():
            add_result(Batch.from_mongodb_doc(document), _search_reason(
                kind="debug", value=query, scope="batch"
            ))
        for document in db.bin.find():
            add_result(Bin.from_mongodb_doc(document), _search_reason(
                kind="debug", value=query, scope="bin"
            ))
    if upper_query == '!BINS':
        for document in db.bin.find():
            add_result(Bin.from_mongodb_doc(document), _search_reason(
                kind="debug", value=query, scope="bin"
            ))
    if upper_query == '!SKUS':
        for document in db.sku.find():
            add_result(Sku.from_mongodb_doc(document), _search_reason(
                kind="debug", value=query, scope="sku"
            ))
    if upper_query == '!BATCHES':
        for document in db.batch.find():
            add_result(Batch.from_mongodb_doc(document), _search_reason(
                kind="debug", value=query, scope="batch"
            ))

    # Human shorthand such as BIN145 resolves to the canonical stored label.
    label_match = re.fullmatch(r"(SKU|BIN|BAT)([0-9]{1,6})", compact_upper_query)
    if label_match:
        prefix, number = label_match.groups()
        canonical_id = f"{prefix}{number.zfill(6)}"
        collection, model = {
            "SKU": (db.sku, Sku),
            "BIN": (db.bin, Bin),
            "BAT": (db.batch, Batch),
        }[prefix]
        add_result(model.from_mongodb_doc(collection.find_one({'_id': canonical_id})),
                   _search_reason(
                       kind="internal-label", value=canonical_id,
                       scope=_search_scope(model),
                   ))

    # Identifier fragments rank before descriptive fragments. A bare numeric
    # query such as 145 can therefore find BIN000145 as well as SKU/BAT labels
    # and other records containing 145.
    fragment = re.compile(re.escape(query), re.IGNORECASE)
    for document in db.bin.find({"_id": fragment}):
        add_result(Bin.from_mongodb_doc(document), _search_reason(
            kind="identifier-fragment", value=document["_id"], scope="bin"
        ))
    for document in db.sku.find({"_id": fragment}):
        add_result(Sku.from_mongodb_doc(document), _search_reason(
            kind="identifier-fragment", value=document["_id"], scope="sku"
        ))
    for document in db.batch.find({"_id": fragment}):
        add_result(Batch.from_mongodb_doc(document), _search_reason(
            kind="identifier-fragment", value=document["_id"], scope="batch"
        ))

    # if not DEV_ENV: # maybe use global flag + env variable instead. Shouldn't need to check this every time in production/
    if "name_text" in db.sku.index_information().keys():
        cursor = db.sku.find({"$text": {"$search": query}})
        for sku_doc in cursor:
            add_result(Sku.from_mongodb_doc(sku_doc), _search_reason(
                kind="name-fragment", value=sku_doc.get("name", ""), scope="sku"
            ))
    if "name_text" in db.batch.index_information().keys():
        cursor = db.batch.find({"$text": {"$search": query}})
        for batch_doc in cursor:
            add_result(Batch.from_mongodb_doc(batch_doc), _search_reason(
                kind="name-fragment", value=batch_doc.get("name", ""), scope="batch"
            ))

    # Mongo text indexes match complete terms. Add a safe escaped fragment
    # pass for the small personal inventory corpus so `hand` finds `handheld`.
    sku_fragment_fields = [
        {"name": fragment},
        {"owned_codes": fragment},
        {"associated_codes": fragment},
    ]
    for sku_doc in db.sku.find({"$or": sku_fragment_fields}):
        model = Sku.from_mongodb_doc(sku_doc)
        if isinstance(sku_doc.get("name"), str) and fragment.search(sku_doc["name"]):
            add_result(model, _search_reason(
                kind="name-fragment", value=sku_doc["name"], scope="sku"
            ))
        for relationship in ("owned", "associated"):
            for value in sku_doc.get(f"{relationship}_codes", []):
                if isinstance(value, str) and fragment.search(value):
                    add_result(model, _search_reason(
                        kind="code-fragment", value=value, scope="sku",
                        relationship=relationship,
                    ))

    batch_fragment_fields = [
        {"name": fragment},
        {"owned_codes": fragment},
        {"associated_codes": fragment},
    ]
    for batch_doc in db.batch.find({"$or": batch_fragment_fields}):
        model = Batch.from_mongodb_doc(batch_doc)
        if isinstance(batch_doc.get("name"), str) and fragment.search(batch_doc["name"]):
            add_result(model, _search_reason(
                kind="name-fragment", value=batch_doc["name"], scope="batch"
            ))
        for relationship in ("owned", "associated"):
            for value in batch_doc.get(f"{relationship}_codes", []):
                if isinstance(value, str) and fragment.search(value):
                    add_result(model, _search_reason(
                        kind="code-fragment", value=value, scope="batch",
                        relationship=relationship,
                    ))

    for observation in db.inventory_code_observations.find({"code": fragment}):
        batch_document = db.batch.find_one({"_id": observation["batch_id"]})
        add_result(Batch.from_mongodb_doc(batch_document), _search_reason(
            kind="code-fragment", value=observation["code"], scope="batch",
            relationship="observed",
        ))

    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps(
        _search_response(hits=hits, starting_from=startingFrom, limit=limit),
        cls=Encoder,
    )
    return resp
