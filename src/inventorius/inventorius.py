from inventorius.util import getIntArgs, admin_get_next
from flask import Blueprint, request, Response, url_for
from voluptuous.error import MultipleInvalid
from inventorius.data_models import Bin, Sku, Batch, DataModelJSONEncoder as Encoder
from inventorius.db import db
from inventorius.validation import item_move_schema, item_release_receive_schema, validate_url_id
import inventorius.util_error_responses as problem
import inventorius.util_success_responses as success
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

    return {"code": code, "usedBy": used_by}


# @inventorius.route('/api/move', methods=['POST'])
# def move_unit_post():
#     oldBin = Bin.from_mongodb_doc(
#         db.bin.find_one({"_id": request.json['from']}))
#     newBin = Bin.from_mongodb_doc(
#         db.bin.find_one({"_id": request.json['to']}))
#     quantity = int(request.json.get('quantity', 1))

#     if 'uniq' in request.json.keys():
#         assert quantity == 1
#         unit = Uniq.from_mongodb_doc(db.uniq.find_one({"id": unit_id}))
#         db.bin.update_one({"_id": oldBin.id},
#                           {"$pull": {"contents.id": unit.id}})
#         db.bin.update_one({"_id": newBin.id},
#                           {"$push": {"contents":
#                                      {"id": unit.id,
#                                       "quantity": 1}}})
#         db.uniq.update_one({"_id": unit.id}, {"bin_id": newBin.id})
#     elif 'sku' in request.json.keys():
#         assert quantity <= oldBin.contentsMap(request.json["sku"])
#         unit = Sku.from_mongodb_doc(
#             db.sku.find_one({"_id": request.json['sku']}))
#         db.bin.update_one({"_id": oldBin.id, "contents.id": unit.id},
#                           {"$inc": {"contents.$.quantity": -quantity}})

#         # if unit not in bin already, add to bin with quantity 0
#         db.bin.update_one({"_id": newBin.id,
#                            "contents": {"$not": {"$elemMatch": {"id": unit.id}}}},
#                           {"$push": {"contents": {"id": unit.id, "quantity": 0}}})
#         db.bin.update_one({"_id": newBin.id, "contents.id": unit.id},
#                           {"$inc": {"contents.$.quantity": quantity}})
#         db.bin.update_many({"$or": [{"_id": newBin.id},
#                                     {"_id": oldBin.id}]},
#                            {"$pull": {"contents": {"quantity": {"$lte": 0}}}})
#     elif 'batch' in request.json.keys():
#         unit = Batch.from_mongodb_doc(db.batch.find_one({"_id": unit_id}))
#         # TODO
#     else:
#         return Response(status=404)
#     return Response(status=200)


@inventorius.route('/api/bin/<id>/contents/move', methods=['PUT'])
@validate_url_id("BIN")
@no_cache
def move_bin_contents_put(id):
    try:
        json = item_move_schema(request.json)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    item_id = json['id']
    destination = json['destination']
    quantity = json['quantity']

    if not db.bin.find_one({"_id": id}):
        return problem.missing_bin_response(id)
    if not db.bin.find_one({"_id": destination}):
        return problem.missing_bin_response(destination)

    if item_id.startswith("SKU"):
        if not db.sku.find_one({"_id": item_id}):
            return problem.missing_sku_response(item_id)
    elif item_id.startswith("BAT"):
        if not db.batch.find_one({"_id": item_id}):
            return problem.missing_batch_response(item_id)

    availible_quantity = Bin.from_mongodb_doc(
        db.bin.find_one({"_id": id})).contents.get(item_id, 0)
    if availible_quantity < quantity:
        return problem.move_insufficient_quantity(
            name="quantity", availible=availible_quantity, requested=quantity)

    db.bin.update_one({"_id": id},
                      {"$inc": {f"contents.{item_id}": - quantity}})
    db.bin.update_one({"_id": destination},
                      {"$inc": {f"contents.{item_id}": quantity}})
    db.bin.update_one({"_id": id, f"contents.{item_id}": 0},
                      {"$unset": {f"contents.{item_id}": ""}})

    return success.moved_response()


@inventorius.route('/api/next/sku', methods=['GET'])
def next_sku():
    resp = Response()
    resp.status_code == 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_sku"),
        "state": admin_get_next("SKU"),
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
    resp = Response()
    resp.status_code == 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_batch"),
        "state": admin_get_next("BAT"),
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
    resp = Response()
    resp.status_code == 200
    resp.mimetype = "application/json"
    resp.data = json.dumps({
        "Id": url_for("inventorius.next_bin"),
        "state": admin_get_next("BIN"),
        "operations": [{
            "rel": "create",
            "method": "POST",
            "href": url_for("bin.bins_post"),
            "Expects-a": "Bin patch",
        }]
    })
    return resp


# @inventorius.route('/api/receive', methods=['POST'])
# def receive_post():
#     form = request.json
#     bin = Bin.from_mongodb_doc(db.bin.find_one({"_id": form['bin_id']}))
#     if not bin:
#         return "Bin not found", 404
#     quantity = int(form.get('quantity', 1))
#     sku_id = form['sku_id']
#     sku = Sku.from_mongodb_doc(db.sku.find_one({"_id": sku_id}))
#     if not sku:
#         return "SKU not found", 404
#     # if unit not in bin already, add to bin with quantity 0
#     db.bin.update_one({"_id": bin.id, "contents": {"$not": {"$elemMatch": {"id": sku.id}}}},
#                       {"$push": {"contents": {"id": sku.id, "quantity": 0}}})
#     db.bin.update_one({"_id": bin.id, "contents.id": sku.id},
#                       {"$inc": {"contents.$.quantity": quantity}})

#     return json.dumps({"sku_id": sku.id, "bin_id": bin.id, "new_quantity": "not implemented"}), 200


@inventorius.route('/api/bin/<bin_id>/contents', methods=["POST"])
@validate_url_id("BIN", param_name="bin_id")
@no_cache
def bin_contents_post(bin_id):
    try:
        json = item_release_receive_schema(request.json)
    except MultipleInvalid as e:
        return problem.invalid_params_response(e)

    item_id = json["id"]
    quantity = json["quantity"]

    if not db.bin.find_one({"_id": bin_id}):
        return problem.missing_bin_response(bin_id)

    if item_id.startswith("SKU"):
        if not db.sku.find_one({"_id": item_id}):
            return problem.missing_sku_response(item_id)
    elif item_id.startswith("BAT"):
        if not db.batch.find_one({"_id": item_id}):
            return problem.missing_batch_response(item_id)

    old_quantity = db.bin.find_one(
        {"_id": bin_id}, {f"contents.{item_id}": 1})["contents"].get(item_id, 0)
    if quantity + old_quantity < 0:
        return problem.release_insufficient_quantity()

    db.bin.update_one({"_id": bin_id},
                        {"$inc": {f"contents.{item_id}": quantity}})

    db.bin.update_one({"_id": bin_id, f"contents.{item_id}": 0},
                        {"$unset": {f"contents.{item_id}": ""}})
    return success.bin_contents_post_response(quantity)



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

    # search for skus with owned_codes
    cursor = db.sku.find({"owned_codes": query})
    for sku_doc in cursor:
        results.append(Sku.from_mongodb_doc(sku_doc))

    # search for skus with associated codes
    cursor = db.sku.find({"associated_codes": query})
    for sku_doc in cursor:
        results.append(Sku.from_mongodb_doc(sku_doc))

    # search for skus with owned_codes
    cursor = db.batch.find({"owned_codes": query})
    for batch_doc in cursor:
        results.append(Batch.from_mongodb_doc(batch_doc))

    # search for batchs with associated codes
    cursor = db.batch.find({"associated_codes": query})
    for batch_doc in cursor:
        results.append(Batch.from_mongodb_doc(batch_doc))

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
