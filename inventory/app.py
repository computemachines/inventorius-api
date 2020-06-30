#! /usr/bin/python3
# -*- coding: utf-8 -*-
"""
    inventory.app
    ~~~~~~~~~~~~~~

    A flask app that implements the inventory api.
    https://app.swaggerhub.com/apis-docs/computemachines/Inventory/2.0.0
"""

from flask import Flask, g, Response, url_for
from flask import request, redirect
import json
import re
import pprint
# from urllib.parse import urlencode

from pymongo import MongoClient
from werkzeug.local import LocalProxy

from inventory.data_models import Bin, MyEncoder, Uniq, Batch, Sku

app = Flask('inventory')
BAD_REQUEST = ('Bad Request', 400)

# memoize mongo_client
_mongo_client = None


def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        db_host = "localhost"
        _mongo_client = MongoClient(db_host, 27017)
        _mongo_client.inventorydb.uniq.create_index('name')
        _mongo_client.inventorydb.sku.create_index('name')

    return _mongo_client


def get_db():
    if 'db' not in g:
        g.db = get_mongo_client().inventorydb
    return g.db


db = LocalProxy(get_db)


def get_body_type():
    if request.mimetype == 'application/json':
        return 'json'
    if request.mimetype in ('application/x-www-form-urlencoded',
                            'multipart/form-data'):
        return 'form'


def admin_increment_code(prefix, code):
    code_number = int(re.sub('[^0-9]', '', code))
    next_unused = int(re.sub('[^0-9]', '', admin_get_next(prefix)))

    if code_number >= next_unused:
        max_code = code_number
        if prefix == "SKU":
            db.admin.replace_one({"_id": "SKU"}, {"_id": "SKU",
                                                  "next": f"SKU{max_code+1:06}"})
        if prefix == "UNIQ":
            db.admin.replace_one({"_id": "UNIQ"}, {"_id": "UNIQ",
                                                   "next": f"UNIQ{max_code+1:05}"})
        if prefix == "BATCH":
            db.admin.replace_one({"_id": "BATCH"}, {"_id": "BATCH",
                                                    "next": f"BATCH{max_code+1:04}"})
        if prefix == "BIN":
            db.admin.replace_one({"_id": "BIN"}, {"_id": "BIN",
                                                  "next": f"BIN{max_code+1:06}"})


def admin_get_next(prefix):

    def max_code_value(collection, prefix):
        cursor = collection.find()
        max_value = 0
        for doc in cursor:
            code_number = int(doc['id'].strip(prefix))
            if code_number > max_value:
                max_value = code_number
        return max_value

    next_code_doc = db.admin.find_one({"_id": prefix})
    if not next_code_doc:
        if prefix == "SKU":
            max_value = max_code_value(db.sku, "SKU")
            db.admin.insert_one({"_id": "SKU",
                                 "next": f"SKU{max_value+1:06}"})
        if prefix == "UNIQ":
            max_value = max_code_value(db.uniq, "UNIQ")
            db.admin.insert_one({"_id": "UNIQ",
                                 "next": f"UNIQ{max_value+1:05}"})
        if prefix == "BATCH":
            max_value = max_code_value(db.batch, "BATCH")
            db.admin.insert_one({"_id": "BATCH",
                                 "next": f"BATCH{max_value+1:04}"})
        if prefix == "BIN":
            max_value = max_code_value(db.bin, "BIN")
            db.admin.insert_one({"_id": "BIN",
                                 "next": f"BIN{max_value+1:06}"})
        next_code_doc = db.admin.find_one({"_id": prefix})
    return next_code_doc['next']


@ app.route('/api/bins', methods=['GET'])
def bins_get():
    args = request.args
    limit = None
    skip = None
    try:
        limit = int(args.get('limit', 20))
        skip = int(args.get('startingFrom', 0))
    except (TypeError, ValueError):
        return BAD_REQUEST

    cursor = db.bin.find()
    cursor.limit(limit)
    cursor.skip(skip)

    bins = [Bin.from_mongodb_doc(bsonBin) for bsonBin in cursor]

    return json.dumps(bins, cls=MyEncoder)


def props_from_form(form):
    pass


# api v2.0.0
@app.route('/api/bins', methods=['POST'])
def bins_post():
    if get_body_type() == 'json':
        bin_json = request.json
    elif get_body_type() == 'form':
        bin_json = {
            'id': request.form['bin_id'],
            'props': props_from_form(request.form)
        }
    bin = Bin.from_json(bin_json)
    admin_increment_code("BIN", bin.id)
    existing = db.bin.find_one({'id': bin.id})

    resp = Response()

    if not bin.id.startswith('BIN'):
        resp.status_code = 400
        resp.data = 'id must start with BIN'
        return resp

    if existing is None:
        db.bin.insert_one(bin.to_mongodb_doc())
        resp.status_code = 201
    else:
        resp.status_code = 409

    if get_body_type() == 'form' and resp.status_code == 201:
        resp.status_code = 302
        resp.headers['Location'] = f"/bin/{bin.id}"

    if get_body_type() == 'json':
        resp.data = bin.to_json()
    print(bin.to_json())
    return resp

# api v2.0.0


@ app.route('/api/bin/<id>', methods=['GET'])
def bin_get(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"id": id}))
    if existing is None:
        return "The bin does not exist", 404
    else:
        return json.dumps(existing, cls=MyEncoder), 200

# api v2.0.0


@ app.route('/api/bin/<id>', methods=['DELETE'])
def bin_delete(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"id": id}))
    if existing is None:
        return "The bin does not exist", 404
    if request.args.get('force', 'false') == 'true' or len(existing.contents) == 0:
        db.bin.delete_one({"id": id})
        return 'Bin was deleted along with all contents, if any.', 200
    else:
        return 'The bin is not empty and force was not set to true.', 403

# api v2.0.0


@ app.route('/api/uniqs', methods=['POST'])
def uniqs_post():
    if get_body_type() == 'json':
        uniq_json = request.json.copy()
    elif get_body_type() == 'form':
        uniq_json = {
            'id': request.form['uniq_id'],
            'bin_id': request.form['bin_id'],
            'owned_codes': request.form['owned_codes'].split(),
            'sku_parent': request.form.get('sku_id', None),
            'name': request.form.get('uniq_name', None)
        }
    uniq = Uniq.from_json(uniq_json)
    bin_id = uniq_json['bin_id']
    bin = Bin.from_mongodb_doc(db.bin.find_one({"id": bin_id}))

    if bin is None:
        return Response("Bin not found", status=404, headers={
            'Location': url_for('bin_get', id=bin_id)})
    if db.uniq.find_one({"id": uniq.id}):
        return Response("Uniq not found", status=409, headers={
            'Location': url_for('uniq_get', id=uniq.id)})

    admin_increment_code("UNIQ", uniq.id)
    db.uniq.insert_one(uniq.to_mongodb_doc())
    db.bin.update_one(
        {"id": bin.id},
        {"$push": {"contents": {"uniq_id": uniq.id, "quantity": 1}}})
    print(f"/uniq/{uniq.id}")
    resp = Response(status=201, headers={
        'Location': f"/uniq/{uniq.id}"})
    if get_body_type() == 'form' and resp.status_code == 201:
        resp.status_code = 302
    return resp

# api v2.0.0


@ app.route('/api/skus', methods=['POST'])
def skus_post():
    sku = Sku.from_json(request.json)

    if db.sku.find_one({'id': sku.id}):
        return Response(status=409, headers={
            'Location': url_for('sku_get', id=sku.id)})

    admin_increment_code("SKU", sku.id)
    db.sku.insert_one(sku.to_mongodb_doc())
    dbSku = Sku.from_mongodb_doc(db.sku.find_one({'id': sku.id}))
    return Response(json.dumps(dbSku, cls=MyEncoder), status=200, headers={
        'Location': url_for('sku_get', id=sku.id)})

# api v2.0.0


@ app.route('/api/sku/<id>', methods=['GET'])
def sku_get(id):
    sku = Sku.from_mongodb_doc(db.sku.find_one({"id": id}))
    if sku is None:
        return 'Sku does not exist.', 404
    return json.dumps(sku, cls=MyEncoder), 200

# api v2.0.0


@ app.route('/api/sku/<id>', methods=['DELETE'])
def sku_delete(id):
    sku = Sku.from_mongodb_doc(db.sku.find_one({"id": id}))

    if sku is None:
        return 'Sku does not exist.', 404

    bins = db.bin.find({"contents.sku_id", sku.id})
    if not bins:
        return 'Must delete all instances of this SKU first.', 403

    db.sku.delete_one({"id": sku.id})
    return Response(status=200)

# api v2.0.0


@ app.route('/api/unit/<id>', methods=['GET'])
def unit_get(id):
    if id.startswith('UNIQ'):
        redirect(url_for('uniq_get', id=id))
    elif id.startswith('SKU'):
        redirect(url_for('sku_get', id=id))
    elif id.startswith('BAT'):
        redirect(url_for('batch_get', id=id))
    else:
        sku = owned_code_get(id)
        if sku:
            redirect(url_for('sku_get', id=sku.id), 307)
        else:
            return Response(status=404)


def owned_code_get(id):
    existing = Sku.from_mongodb_doc(
        db.sku.find_one({'owned_codes': id}))
    return existing

# api v2.0.0


@ app.route('/api/uniq/<id>', methods=['GET'])
def uniq_get(id):
    uniq = Uniq.from_mongodb_doc(db.uniq.find_one({"id": id}))
    if not uniq:
        return Response(status=404)
    return uniq.to_json(), 200

# api v2.0.0


@ app.route('/api/uniq/<id>', methods=['DELETE'])
def uniq_delete(id):
    uniq = Uniq.from_mongodb_doc(db.uniq.find_one({"id": id}))
    if not uniq:
        return 'The unit does not exist so can not be deleted.', 404

    db.uniq.delete_one({"id": uniq.id})
    db.bin.update_one({"contents.uniq_id": uniq.id},
                      {"$pull": {"uniq_id": uniq.id}})
    return Response(status=200)

# api v2.0.0


@ app.route('/api/move-units', methods=['POST'])
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
                          {"$pull": {"contents.uniq_id": unit.id}})
        db.bin.update_one({"id": newBin.id},
                          {"$push": {"contents":
                                     {"uniq_id": unit.id,
                                      "quantity": 1}}})
        db.uniq.update_one({"id": unit.id}, {"bin_id": newBin.id})
    elif unit_id.startswith('SKU'):
        assert quantity <= oldBin.skus()[unit_id]
        unit = Sku.from_mongodb_doc(db.sku.find_one({"id": unit_id}))
        db.bin.update_one({"id": oldBin.id, "contents.sku_id": unit.id},
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

# api v2.0.0


@ app.route('/api/receive', methods=['POST'])
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


def getIntArgs(args, name, default):
    str_value = args.get(name, default)
    try:
        value = int(str_value)
    except ValueError:
        value = default
    return value


@ app.route('/api/search', methods=['GET'])
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
        result = Sku.from_mongodb_doc(db.sku.find({'id': query}))
    if query.startswith('UNIQ'):
        result = Uniq.from_mongodb_doc(db.uniq.find({'id': query}))
    if query.startswith('BIN'):
        result = Bin.from_mongodb_doc(db.bin.find_one({'id': query}))
    if query.startswith('BATCH'):
        result = Batch.from_mongodb_doc(db.batch.find({'id': query}))
    if result:
        results.append(result)

    cursor = db.sku.find({"$or": [{"id": query},
                                  {"owned_codes": query}]})
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


@ app.route('/api/next/sku', methods=['GET'])
def next_sku():
    return admin_get_next("SKU")


@ app.route('/api/next/uniq', methods=['GET'])
def next_uniq():
    return admin_get_next("UNIQ")


@ app.route('/api/next/batch', methods=['GET'])
def next_batch():
    return admin_get_next("BATCH")


@ app.route('/api/next/bin', methods=['GET'])
def next_bin():
    return admin_get_next("BIN")


if __name__ == '__main__':
    app.run(port=8081, debug=True)
