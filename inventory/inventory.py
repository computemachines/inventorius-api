from inventory.util import getIntArgs
from flask import Blueprint, request, Response
from inventory.data_models import Bin, Sku, Uniq, DataModelJSONEncoder as Encoder
from inventory.db import db

import json

inventory = Blueprint("inventory", __name__)


@ inventory.route('/api/move', methods=['POST'])
def move_unit_post():
    oldBin = Bin.from_mongodb_doc(
        db.bin.find_one({"_id": request.json['from']}))
    newBin = Bin.from_mongodb_doc(
        db.bin.find_one({"_id": request.json['to']}))
    quantity = int(request.json.get('quantity', 1))

    if 'uniq' in request.json.keys():
        assert quantity == 1
        unit = Uniq.from_mongodb_doc(db.uniq.find_one({"id": unit_id}))
        db.bin.update_one({"_id": oldBin.id},
                          {"$pull": {"contents.id": unit.id}})
        db.bin.update_one({"_id": newBin.id},
                          {"$push": {"contents":
                                     {"id": unit.id,
                                      "quantity": 1}}})
        db.uniq.update_one({"_id": unit.id}, {"bin_id": newBin.id})
    elif 'sku' in request.json.keys():
        assert quantity <= oldBin.contentsMap(request.json["sku"])
        unit = Sku.from_mongodb_doc(
            db.sku.find_one({"_id": request.json['sku']}))
        db.bin.update_one({"_id": oldBin.id, "contents.id": unit.id},
                          {"$inc": {"contents.$.quantity": -quantity}})

        # if unit not in bin already, add to bin with quantity 0
        db.bin.update_one({"_id": newBin.id,
                           "contents": {"$not": {"$elemMatch": {"id": unit.id}}}},
                          {"$push": {"contents": {"id": unit.id, "quantity": 0}}})
        db.bin.update_one({"_id": newBin.id, "contents.id": unit.id},
                          {"$inc": {"contents.$.quantity": quantity}})
        db.bin.update_many({"$or": [{"_id": newBin.id},
                                    {"_id": oldBin.id}]},
                           {"$pull": {"contents": {"quantity": {"$lte": 0}}}})
    elif 'batch' in request.json.keys():
        unit = Batch.from_mongodb_doc(db.batch.find_one({"_id": unit_id}))
        # TODO
    else:
        return Response(status=404)
    return Response(status=200)


@ inventory.route('/api/next/sku', methods=['GET'])
def next_sku():
    return admin_get_next("SKU")


@ inventory.route('/api/next/uniq', methods=['GET'])
def next_uniq():
    return admin_get_next("UNIQ")


@ inventory.route('/api/next/batch', methods=['GET'])
def next_batch():
    return admin_get_next("BATCH")


@ inventory.route('/api/next/bin', methods=['GET'])
def next_bin():
    return admin_get_next("BIN")


@ inventory.route('/api/receive', methods=['POST'])
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


@ inventory.route('/api/search', methods=['GET'])
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
