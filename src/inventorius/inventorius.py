from inventorius.util import (
    IdentifierSpaceExhausted,
    admin_get_next,
    getIntArgs,
)
from flask import Blueprint, request, Response, url_for
from inventorius.data_models import Bin, Sku, Batch, DataModelJSONEncoder as Encoder
from inventorius.db import db
import inventorius.util_error_responses as problem
from inventorius.util import no_cache

import json
import re

inventorius = Blueprint("inventorius", __name__)


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
@no_cache
def move_bin_contents_put(id):
    # CUT-01 deliberately ends the mutable bin.contents accounting path. The
    # read adapters remain available, but all new movement is an immutable
    # ledger operation through /api/inventory-operations.
    return problem.operation_retired_response()


@inventorius.route('/api/next/sku', methods=['GET'])
def next_sku():
    try:
        next_id = admin_get_next("SKU")
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    resp = Response()
    resp.status_code == 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_sku"),
        "state": next_id,
        "operations": [{
            "rel": "create",
            "method": "POST",
            "href": url_for("sku.skus_post"),
            "Expects-a": "Sku patch",
        }]
    })
    return resp

@inventorius.route('/api/next/batch', methods=['GET'])
def next_batch():
    try:
        next_id = admin_get_next("BAT")
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    resp = Response()
    resp.status_code == 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_batch"),
        "state": next_id,
        "operations": [{
            "rel": "create",
            "method": "POST",
            "href": url_for("batch.batches_post"),
            "Expects-a": "Batch patch",
        }]
    })
    return resp


@inventorius.route('/api/next/bin', methods=['GET'])
def next_bin():
    try:
        next_id = admin_get_next("BIN")
    except IdentifierSpaceExhausted as error:
        return problem.identifier_space_exhausted_response(error.prefix)

    resp = Response()
    resp.status_code == 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_bin"),
        "state": next_id,
        "operations": [{
            "rel": "create",
            "method": "POST",
            "href": url_for("bin.bins_post"),
            "Expects-a": "Bin patch",
        }]
    })
    return resp



@inventorius.route('/api/bin/<bin_id>/contents', methods=["POST"])
@no_cache
def bin_contents_post(bin_id):
    # This route used to make the ledger and bin.contents disagree. It is
    # deliberately retained only as a clear migration error.
    return problem.operation_retired_response()


@inventorius.route('/api/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip()
    upper_query = query.upper()
    limit = max(1, min(getIntArgs(request.args, "limit", 20), 100))
    startingFrom = max(0, getIntArgs(request.args, "startingFrom", 0))
    resp = Response()

    results = []

    if not query:
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps({'state': {
            "total_num_results": 0,
            "starting_from": startingFrom,
            "limit": limit,
            "returned_num_results": 0,
            "results": []
        }, "operations": []})
        return resp

    # An exact external code is stronger evidence than a coincidental text or
    # identifier match.  A scanner should return only the resources that
    # explicitly carry the code, even where the code is shared.
    exact_code_results = []
    exact_resource_ids = set()

    def add_exact_code_result(model, document):
        if document is None:
            return
        resource_key = (model.__name__, document["_id"])
        if resource_key not in exact_resource_ids:
            exact_resource_ids.add(resource_key)
            exact_code_results.append(model.from_mongodb_doc(document))

    for sku_document in db.sku.find({"$or": [
        {"owned_codes": query}, {"associated_codes": query},
    ]}):
        add_exact_code_result(Sku, sku_document)
    for batch_document in db.batch.find({"$or": [
        {"owned_codes": query}, {"associated_codes": query},
    ]}):
        add_exact_code_result(Batch, batch_document)
    for observation in db.inventory_code_observations.find({"code": query}):
        add_exact_code_result(
            Batch, db.batch.find_one({"_id": observation["batch_id"]})
        )

    if exact_code_results:
        paged = exact_code_results[startingFrom:(startingFrom + limit)]
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps({'state': {
            "total_num_results": len(exact_code_results),
            "starting_from": startingFrom,
            "limit": limit,
            "returned_num_results": len(paged),
            "results": paged
        }, "operations": []}, cls=Encoder)
        return resp

    # debug flags
    if upper_query == '!ALL':
        results.extend([Sku.from_mongodb_doc(e) for e in db.sku.find()])
        results.extend([Batch.from_mongodb_doc(e) for e in db.batch.find()])
        results.extend([Bin.from_mongodb_doc(e) for e in db.bin.find()])
    if upper_query == '!BINS':
        results.extend([Bin.from_mongodb_doc(e) for e in db.bin.find()])
    if upper_query == '!SKUS':
        results.extend([Sku.from_mongodb_doc(e) for e in db.sku.find()])
    if upper_query == '!BATCHES':
        results.extend([Batch.from_mongodb_doc(e) for e in db.batch.find()])

    # Human shorthand such as BIN145 resolves to the canonical stored label.
    label_match = re.fullmatch(r"(SKU|BIN|BAT)([0-9]{1,6})", upper_query)
    if label_match:
        prefix, number = label_match.groups()
        canonical_id = f"{prefix}{number.zfill(6)}"
        collection, model = {
            "SKU": (db.sku, Sku),
            "BIN": (db.bin, Bin),
            "BAT": (db.batch, Batch),
        }[prefix]
        results.append(model.from_mongodb_doc(
            collection.find_one({'_id': canonical_id})))
    results = [result for result in results if result != None]

    # Identifier fragments rank before descriptive fragments. A bare numeric
    # query such as 145 can therefore find BIN000145 as well as SKU/BAT labels
    # and other records containing 145.
    fragment = re.compile(re.escape(query), re.IGNORECASE)
    for document in db.bin.find({"_id": fragment}):
        results.append(Bin.from_mongodb_doc(document))
    for document in db.sku.find({"_id": fragment}):
        results.append(Sku.from_mongodb_doc(document))
    for document in db.batch.find({"_id": fragment}):
        results.append(Batch.from_mongodb_doc(document))

    # if not DEV_ENV: # maybe use global flag + env variable instead. Shouldn't need to check this every time in production/
    if "name_text" in db.sku.index_information().keys():
        cursor = db.sku.find({"$text": {"$search": query}})
        for sku_doc in cursor:
            results.append(Sku.from_mongodb_doc(sku_doc))
    if "name_text" in db.batch.index_information().keys():
        cursor = db.batch.find({"$text": {"$search": query}})
        for batch_doc in cursor:
            results.append(Batch.from_mongodb_doc(batch_doc))

    # Mongo text indexes match complete terms. Add a safe escaped fragment
    # pass for the small personal inventory corpus so `hand` finds `handheld`.
    sku_fragment_fields = [
        {"name": fragment},
        {"owned_codes": fragment},
        {"associated_codes": fragment},
    ]
    for sku_doc in db.sku.find({"$or": sku_fragment_fields}):
        results.append(Sku.from_mongodb_doc(sku_doc))

    batch_fragment_fields = [
        {"name": fragment},
        {"owned_codes": fragment},
        {"associated_codes": fragment},
    ]
    for batch_doc in db.batch.find({"$or": batch_fragment_fields}):
        results.append(Batch.from_mongodb_doc(batch_doc))

    for observation in db.inventory_code_observations.find({"code": fragment}):
        results.append(Batch.from_mongodb_doc(
            db.batch.find_one({"_id": observation["batch_id"]})
        ))

    # Exact IDs and codes can overlap, so keep one row per resource.
    unique_results = {}
    for result in results:
        if result is not None:
            unique_results[(type(result).__name__, result.id)] = result
    results = list(unique_results.values())

    if results != []:
        paged = results[startingFrom:(startingFrom + limit)]
        resp.status_code = 200
        resp.mimetype = "application/json"
        # TODO: Add next page / prev page operations
        resp.data = json.dumps({'state': {
            "total_num_results": len(results),
            "starting_from": startingFrom,
            "limit": limit,
            "returned_num_results": len(paged),
            "results": paged
        },
            "operations": []}, cls=Encoder)
        return resp

    resp.status_code = 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({'state': {
        "total_num_results": len(results),
        "starting_from": startingFrom,
        "limit": limit,
        "returned_num_results": 0,
        "results": []
    }, "operations": []}, cls=Encoder)
    return resp
