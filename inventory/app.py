#! /usr/bin/python3

import sys
print(sys.path)


from flask import Flask, g, appcontext_pushed, Response, url_for
from flask import request, redirect
from flask.json import jsonify
import json
from bson.json_util import dumps
from urllib.parse import urlencode

from pymongo import MongoClient, IndexModel, TEXT
from pymongo.errors import ConnectionFailure
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

# api v1.0.0
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

    cursor = db.bins.find()
    cursor.limit(limit)
    cursor.skip(skip)

    bins = [Bin.from_mongodb_doc(bsonBin) for bsonBin in cursor]
    
    return json.dumps(bins, cls=MyEncoder)

# api v1.0.0
@app.route('/api/bins', methods=['POST'])
def bins_post():
    bin = Bin.from_json(request.json)
    existing = db.bins.find_one({'id': bin.id})
    resp = Response()
    if existing is None:
        db.bins.insert_one(bin.to_mongodb_doc())
        resp.status_code = 201
    else:
        resp.status_code = 409
    resp.headers['Location'] = url_for('bin_get', id=bin.id)
    return resp

# api v1.0.0
@app.route('/api/bin/<id>', methods=['GET'])
def bin_get(id):
    existing = Bin.from_mongodb_doc(db.bins.find_one({"id": id}))
    if existing is None:
        return "The bin does not exist", 404
    else:
        return bin.to_json(), 200

@app.route('/api/units', methods=['GET'])
def units_get():
    return json.dumps([], cls=MyEncoder)

@app.route('/api/unit/<id>', methods=['GET'])
def unit_get(id):
    existing = None
    if id.startswith('UNIQ'):
        existing = uniq_get(id)
    elif id.startswith('SKU'):
        existing = sku_get(id)
    elif id.startswith('BAT'):
        existing = batch_get(id)
    else:
        sku = owned_code_get(id)
        resp = Response()
        resp.status_code = 302
        resp.headers['Location'] = url_for('unit_get', id=sku.id)
        return resp

    if existing is None:
        resp = Response()
        resp.status_code = 404
        return resp

    return existing.to_json(), 200

def uniq_get(id):
    existing = Uniq.from_mongodb_doc(db.uniq.find_one({'id': id}))
    return existing
def sku_get(id):
    existing = Sku.from_mongodb_doc(db.sku.find_one({'id': id}))
    return existing
def batch_get(id):
    existing = Batch.from_mongodb_doc(db.batch.find_one({'id': id}))
    return existing
def owned_code_get(id):
    existing = Sku.from_mongodb_doc(
        db.sku.find_one({'owned_codes': id}))
    return existing

# api v2.0.0
@app.route('/api/units/uniqs', methods=['POST'])
def uniq_post():
    uniq = Uniq.from_json(request.json)
    existing = db.uniq.find_one({'id': uniq.id})
    resp = Response()
    if existing is None:
        db.uniq.insert_one(uniq.to_mongodb_doc())
        resp.status_code = 201
    else:
        resp.status_code = 409
        resp.headers['Location'] = url_for('unit_get', id=uniq.id)
    return resp
    
if __name__=='__main__':
    app.run(port=8081, debug=True)
