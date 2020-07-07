from flask import Blueprint, request
from inventory.data_models import Bin, DataModelJSONEncoder as Encoder
from inventory.db import db

import json

inventory = Blueprint("inventory", __name__)


@ inventory.route('/api/move-units', methods=['POST'])
def move_unit_post():
    oldBin = Bin.from_mongodb_doc(
        db.bin.find_one({"id": request.form['old_bin_id']}))
    newBin = Bin.from_mongodb_doc(
        db.bin.find_one({"id": request.form['new_bin_id']}))
    quantity = int(request.form.get('quantity', 1))
    unit_id = request.form['unit_id']

    if unit_id.startswith('UNIQ'):
        assert quantity == 1
        unit = Uniq.from_mongodb_doc(db.uniq.find_one({"id": unit_id}))
        db.bin.update_one({"id": oldBin.id},
                          {"$pull": {"contents.id": unit.id}})
        db.bin.update_one({"id": newBin.id},
                          {"$push": {"contents":
                                     {"id": unit.id,
                                      "quantity": 1}}})
        db.uniq.update_one({"id": unit.id}, {"bin_id": newBin.id})
    elif unit_id.startswith('SKU'):
        assert quantity <= oldBin.skus()[unit_id]
        unit = Sku.from_mongodb_doc(db.sku.find_one({"id": unit_id}))
        db.bin.update_one({"id": oldBin.id, "contents.id": unit.id},
                          {"$inc": {"contents.$.quantity": -quantity}})

        # if unit not in bin already, add to bin with quantity 0
        db.bin.update_one({"id": newBin.id,
                           "contents": {"$not": {"$elemMatch": {"sku_id": unit.id}}}},
                          {"$push": {"contents": {"sku_id": unit.id, "quantity": 0}}})
        db.bin.update_one({"id": newBin.id, "contents.sku_id": unit.id},
                          {"$inc": {"contents.$.quantity": quantity}})
        db.bin.update_many({"$or": [{"id": newBin.id},
                                    {"id": oldBin.id}]},
                           {"$pull": {"contents": {"quantity": {"$lte": 0}}}})
    elif unit_id.startswith('BAT'):
        unit = Batch.from_mongodb_doc(db.batch.find_one({"id": unit_id}))
        # TODO
    else:
        unit = owned_code_get(id)
        # TODO
    if not unit:
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
    bin = Bin.from_mongodb_doc(db.bin.find_one({"id": form['bin_id']}))
    if not bin:
        return "Bin not found", 404
    quantity = int(form.get('quantity', 1))
    sku_id = form['sku_id']
    sku = Sku.from_mongodb_doc(db.sku.find_one({"id": sku_id}))
    if not sku:
        return "SKU not found", 404
    # if unit not in bin already, add to bin with quantity 0
    db.bin.update_one({"id": bin.id, "contents": {"$not": {"$elemMatch": {"sku_id": sku.id}}}},
                      {"$push": {"contents": {"sku_id": sku.id, "quantity": 0}}})
    db.bin.update_one({"id": bin.id, "contents.sku_id": sku.id},
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

    if results != []:
        paged = results[startingFrom:(startingFrom+limit)]
        return json.dumps({
            "total_num_results": len(results),
            "starting_from": startingFrom,
            "limit": limit,
            "returned_num_results": len(paged),
            "results": paged
        }, cls=MyEncoder)

    return json.dumps({
        "total_num_results": len(results),
        "starting_from": startingFrom,
        "limit": limit,
        "returned_num_results": 0,
        "results": []
    }, cls=MyEncoder)
