from inventory.util import getIntArgs, admin_get_next
from flask import Blueprint, request, Response
from inventory.data_models import Bin, Sku, Batch, DataModelJSONEncoder as Encoder
from inventory.db import db

import json

inventory = Blueprint("inventory", __name__)


# @inventory.route('/api/move', methods=['POST'])
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


@inventory.route('/api/bin/<id>/contents/move', methods=['PUT'])
def move_bin_contents_put(id):
    resp = Response()
    item_id = request.json['id']
    destination = request.json['destination']
    quantity = request.json['quantity']

    db.bin.update_one({"_id": id},
                      {"$inc": {f"contents.{item_id}": - quantity}})
    db.bin.update_one({"_id": destination},
                      {"$inc": {f"contents.{item_id}": quantity}})
    db.bin.update_one({"_id": id, f"contents.{item_id}": 0},
                      {"$unset": {f"contents.{item_id}": ""}})
    resp.status_code = 204
    resp.headers['Cache-Control'] = 'no-cache'

    return resp


@inventory.route('/api/next/sku', methods=['GET'])
def next_sku():
    return admin_get_next("SKU")


@inventory.route('/api/next/uniq', methods=['GET'])
def next_uniq():
    return admin_get_next("UNIQ")


@inventory.route('/api/next/batch', methods=['GET'])
def next_batch():
    return admin_get_next("BATCH")


@inventory.route('/api/next/bin', methods=['GET'])
def next_bin():
    return admin_get_next("BIN")


@inventory.route('/api/receive', methods=['POST'])
def receive_post():
    form = request.json
    bin = Bin.from_mongodb_doc(db.bin.find_one({"_id": form['bin_id']}))
    if not bin:
        return "Bin not found", 404
    quantity = int(form.get('quantity', 1))
    sku_id = form['sku_id']
    sku = Sku.from_mongodb_doc(db.sku.find_one({"_id": sku_id}))
    if not sku:
        return "SKU not found", 404
    # if unit not in bin already, add to bin with quantity 0
    db.bin.update_one({"_id": bin.id, "contents": {"$not": {"$elemMatch": {"id": sku.id}}}},
                      {"$push": {"contents": {"id": sku.id, "quantity": 0}}})
    db.bin.update_one({"_id": bin.id, "contents.id": sku.id},
                      {"$inc": {"contents.$.quantity": quantity}})

    return json.dumps({"sku_id": sku.id, "bin_id": bin.id, "new_quantity": "not implemented"}), 200


@inventory.route('/api/bin/<id>/contents', methods=["POST"])
def bin_contents_post(id):
    into_bin = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    item_id = request.json['id']
    quantity = request.json['quantity']
    resp = Response()
    resp.headers = {"Cache-Control": "no-cache"}

    if not into_bin:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "Can not receive items into a bin that does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an exisiting bin id"
            }]
        })
        return resp

    if item_id.startswith("SKU"):
        exisiting_sku = Sku.from_mongodb_doc(db.sku.find_one({"_id": item_id}))
        if not exisiting_sku:
            resp.status_code = 409
            resp.mimetype = "application/problem+json"
            resp.data = json.dumps({
                "type": "missing-resource",
                "title": "Can not receive sku that does not exist.",
                "invalid-params": [{
                    "name": "item_id",
                    "reason": "must be an exisiting batch or sku id"
                }]
            })
            return resp
        else:
            db.bin.update_one({"_id": into_bin.id},
                              {"$inc": {f"contents.{item_id}": quantity}})
            resp.status_code = 201
            return resp
    elif item_id.startswith("BAT"):
        existing_batch = Batch.from_mongodb_doc(
            db.batch.find_one({"_id": item_id}))
        if not existing_batch:
            resp.status_code = 409
            resp.mimetype = "application/problem+json"
            resp.data = json.dumps({
                "type": "missing-resource",
                "title": "Can not receive batch that does not exist.",
                "invalid-params": [{
                    "name": "item_id",
                    "reason": "must be an exisiting batch or sku id"
                }]
            })
            return resp
        else:
            db.bin.update_one({"_id": into_bin.id},
                              {"$inc": {f"contents.{item_id}": quantity}})
            resp.status_code = 201
            return resp
    else:
        resp.status_code = 409
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "bad-id-format",
            "title": "Received item id must be a batch or sku.",
            "invalid-params": [{
                "name": "item_id",
                "reason": "must be an exisiting batch or sku id"
            }]
        })
        return resp


@inventory.route('/api/search', methods=['GET'])
def search():
    query = request.args['query']
    limit = getIntArgs(request.args, "limit", 20)
    startingFrom = getIntArgs(request.args, "startingFrom", 0)
    results = []

    # debug flags
    if query == '!ALL':
        results.extend([Uniq.from_mongodb_doc(e) for e in db.uniq.find()])
        results.extend([Sku.from_mongodb_doc(e) for e in db.sku.find()])
        results.extend([Batch.from_mongodb_doc(e) for e in db.batch.find()])
        results.extend([Bin.from_mongodb_doc(e) for e in db.bin.find()])
    if query == '!BINS':
        results.extend([Bin.from_mongodb_doc(e) for e in db.bin.find()])
    if query == '!SKUS':
        results.extend([Sku.from_mongodb_doc(e) for e in db.sku.find()])
    if query == '!UNIQS':
        results.extend([Uniq.from_mongodb_doc(e) for e in db.uniq.find()])
    if query == '!BATCHES':
        results.extend([Batch.from_mongodb_doc(e) for e in db.batch.find()])

    # search by label
    if query.startswith('SKU'):
        results.append(Sku.from_mongodb_doc(db.sku.find_one({'id': query})))
    if query.startswith('UNIQ'):
        results.append(Uniq.from_mongodb_doc(db.uniq.find_one({'id': query})))
    if query.startswith('BIN'):
        results.append(Bin.from_mongodb_doc(db.bin.find_one({'id': query})))
    if query.startswith('BATCH'):
        results.append(Batch.from_mongodb_doc(
            db.batch.find_one({'id': query})))
    results = [result for result in results if result != None]

    # search for skus with owned_codes
    cursor = db.sku.find({"owned_codes": query})
    for sku_doc in cursor:
        results.append(Sku.from_mongodb_doc(sku_doc))

    # search for skus with associated codes
    cursor = db.sku.find({"associated_codes": query})
    for sku_doc in cursor:
        results.append(Sku.from_mongodb_doc(sku_doc))

    cursor = db.sku.find({"$text": {"$search": query}})
    for sku_doc in cursor:
        results.append(Sku.from_mongodb_doc(sku_doc))

    cursor = db.uniq.find({"$text": {"$search": query}})
    for uniq_doc in cursor:
        results.append(Uniq.from_mongodb_doc(uniq_doc))

    if results != []:
        paged = results[startingFrom:(startingFrom+limit)]
        return json.dumps({
            "total_num_results": len(results),
            "starting_from": startingFrom,
            "limit": limit,
            "returned_num_results": len(paged),
            "results": paged
        }, cls=Encoder)

    return json.dumps({
        "total_num_results": len(results),
        "starting_from": startingFrom,
        "limit": limit,
        "returned_num_results": 0,
        "results": []
    }, cls=Encoder)
