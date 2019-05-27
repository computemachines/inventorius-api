#! /usr/bin/python3
# -*- coding: utf-8 -*-
"""
    inventory.app
    ~~~~~~~~~~~~~~

    A flask app that implements the inventory api.
    https://app.swaggerhub.com/apis-docs/computemachines/Inventory/2.0.0
"""

from flask import Flask, g, appcontext_pushed, Response, url_for
from flask import request, redirect
from flask.json import jsonify
import json
from bson.json_util import dumps
from urllib.parse import urlencode

from pymongo import MongoClient
from werkzeug.local import LocalProxy

from inventory.data_models import Bin, MyEncoder, Uniq, Batch, Sku

app = Flask('inventory')
app.config['LOCAL_MONGO'] = app.debug or app.testing
# app.config['SERVER_ROOT'] = 'https://computemachines.com'

# memoize mongo_client
_mongo_client = None
def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        if app.config.get('LOCAL_MONGO', False):
            db_host = "localhost"
        else:
            db_host = "mongo"
            # import time
            # time.sleep(20)
        _mongo_client = MongoClient(db_host, 27017)
    return _mongo_client

def get_db():
    if 'db' not in g:
        g.db = get_mongo_client().inventorydb
    return g.db
db = LocalProxy(get_db)

# api v2.0.0
@app.route('/api/bins', methods=['GET'])
def bins_get():
    args = request.args
    limit = None
    skip = None
    try:
        limit = int(args.get('limit', 20))
        skip = int(args.get('startingFrom', 0))
    except:
        return "Malformed Request. Possible pagination query parameter constraint violation.", 400

    cursor = db.bin.find()
    cursor.limit(limit)
    cursor.skip(skip)

    bins = [Bin.from_mongodb_doc(bsonBin) for bsonBin in cursor]

    return json.dumps(bins, cls=MyEncoder)

# api v2.0.0
@app.route('/api/bins', methods=['POST'])
def bins_post():
    bin = Bin.from_json(request.json)
    existing = db.bin.find_one({'id': bin.id})
    resp = Response()
    if existing is None:
        db.bin.insert_one(bin.to_mongodb_doc())
        resp.status_code = 201
    else:
        resp.status_code = 409
    resp.headers['Location'] = url_for('bin_get', id=bin.id)
    return resp

# api v2.0.0
@app.route('/api/bin/<id>', methods=['GET'])
def bin_get(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"id": id}))
    if existing is None:
        return "The bin does not exist", 404
    else:
        return json.dumps(existing, cls=MyEncoder), 200

# api v2.0.0
@app.route('/api/bin/<id>', methods=['DELETE'])
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
@app.route('/api/bin/<bin_id>/uniqs', methods=['POST'])
def uniqs_post(bin_id):
    bin = Bin.from_mongodb_doc(db.bin.find_one({"id": bin_id}))
    uniq_json = request.json.copy()
    uniq_json['bin_id'] = bin_id
    uniq = Uniq.from_json(uniq_json)

    if bin is None:
        return Response(status=404, headers={
            'Location', url_for('bin_get', id=bin_id)})
    if db.uniq.find_one({"id": uniq.id}):
        return Response(status=409, headers={
            'Location': url_for('uniq_get', id=uniq.id)})

    db.uniq.insert_one(uniq.to_mongo_doc())
    db.bin.update_one(
        {"id": bin.id},
        {"$push": {contents: {"uniq_id": uniq.id, "quantity": 1}}})
    return Response(status=201, headers={
        'Location': url_for('unit_get', id=uniq.id)})


# api v2.0.0
@app.route('/api/skus', methods=['POST'])
def skus_post():
    sku = Sku.from_json(request.json)
    if len(sku.owned_codes) == 0 or sku.owned_codes[0] != sku.id:
        sku.owned_codes.insert(0, sku.id)

    if db.sku.find_one({'id': sku.id}):
        return Response(status=409, headers={
            'Location': url_for('sku_get', id=sku.id)})

    db.sku.insert_one(sku.to_mongo_doc())
    return Response(status=200, headers={
        'Location': url_for('sku_get', id=sku.id)})

# api v2.0.0
@app.route('/api/sku/<id>', methods=['GET'])
def sku_get(id):
    sku = Sku.from_mongo_doc(db.sku.find_one({"id": id}))
    if sku is None:
        return 'Sku does not exist.', 404
    return json.dumps(sku, cls=MyEncoder), 200

# api v2.0.0
@app.route('/api/sku/<id>', methods=['DELETE'])
def sku_delete(id):
    sku = Sku.from_mongo_doc(db.sku.find_one({"id": id}))

    if sku is None:
        return 'Sku does not exist.', 404

    bins = db.bin.find({"contents.sku_id", sku.id})
    if not bins:
        return 'Must delete all instances of this SKU first.', 403

    db.sku.delete_one({"id": sku.id})
    return Response(status=200)

# api v2.0.0
@app.route('/api/unit/<id>', methods=['GET'])
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
@app.route('/api/uniq/<id>', methods=['GET'])
def uniq_get(id):
    uniq = Uniq.from_mongodb_doc(db.uniq.find_one({"id": id}))
    if not uniq:
        return Response(status=404)
    return uniq.to_json(), 200

# api v2.0.0
@app.route('/api/uniq/<id>', methods=['DELETE'])
def uniq_delete(id):
    uniq = Uniq.from_mongodb_doc(db.uniq.find_one({"id": id}))
    if not uniq:
        return 'The unit does not exist so can not be deleted.', 404

    db.uniq.delete_one({"id": uniq.id})
    db.bin.update_one({"contents.uniq_id": uniq.id},
                      {"$pull": {"uniq_id": uniq.id}})
    return Response(status=200)

# api v2.0.0
@app.route('/api/move-unit', methods=['POST'])
def move_unit_post():
    oldBin = Bin.from_mongodb_doc(db.bin.find({"id": request.form['old_bin_id']}))
    newBin = Bin.from_mongodb_doc(db.bin.find({"id": request.form['new_bin_id']}))
    quantity = int(request.form.get('quantity', 1))
    unit_id = request.form['unit_id']

    if id.startswith('UNIQ'):
        assert quantity == 1
        unit = Uniq.from_mongodb_doc(db.uniq.find({"id": unit_id}))
        db.bin.update_one({"id": oldBin.id},
                          {"$pull": {"contents.uniq_id": unit.id}})
        db.bin.update_one({"id": newBin.id},
                          {"$push": {"contents":
                                     {"uniq_id": unit.id,
                                      "quantity": 1}}})
        db.uniq.update_one({"id": unit.id}, {"bin_id": newBin.id})
    elif id.startswith('SKU'):
        assert quantity <= oldBin.skus()[unit_id]
        unit = Sku.from_mongodb_doc(db.sku.find({"id": unit_id}))
        db.bin.update_one({"id": oldBin.id, "content.sku_id": unit.id},
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
    elif id.startswith('BAT'):
        unit = Batch.from_mongodb_doc(db.batch.find({"id": unit_id}))
        # TODO
    else:
        unit = owned_code_get(id)
        # TODO
    if not unit:
        return Response(status=404)

# api v2.0.0
@app.route('/api/receive', methods=['POST'])
def receive_post():
    bin = Bin.from_mongodb_doc(db.bin.find({"id": request.form['bin_id']}))
    quantity = int(request.form.get('quantity', 1))
    sku_id = request.form['sku_id']
    sku = Sku.from_mongodb_doc(db.sku.find({"id": sku_id}))

    # if unit not in bin already, add to bin with quantity 0
    db.bin.update_one({"id": bin.id, "contents": {"$not": {"$elemMatch": {"sku_id": sku.id}}}},
                      {"$push": {"contents": {"sku_id": sku.id, "quantity": 0}}})
    db.bin.update_one({"id": bin.id, "contents.sku_id": sku.id},
                      {"$inc": {"contents.$.quantity": quantity}})

    return Response(status=200)


if __name__ == '__main__':
    app.run(port=8081, debug=True)
