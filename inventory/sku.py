from flask import Blueprint, request, Response, url_for
from inventory.data_models import Sku, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import admin_increment_code

import json

sku = Blueprint("sku", __name__)


@ sku.route('/api/skus', methods=['POST'])
def skus_post():
    resp = Response()

    sku = Sku.from_json(request.json)

    if not sku.id.startswith('SKU'):
        resp.status_code = 400
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "bad-id-format",
            "title": "Sku Ids must start with 'SKU'.",
            "invalid-params": [{
                "name": "id",
                "reason": "must start with string 'SKU'"
            }]})
        return resp

    if db.sku.find_one({'_id': sku.id}):
        resp.status_code = 409
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "duplicate-resource",
            "title": "A Sku with this Id already exists.",
            "invalid-params": [{
                "name": "id",
                "reason": "must not be an existing sku id"
            }]
        })
        resp.headers['Location'] = url_for('sku.sku_get', id=sku.id)
        return resp

    admin_increment_code("SKU", sku.id)
    db.sku.insert_one(sku.to_mongodb_doc())
    dbSku = Sku.from_mongodb_doc(db.sku.find_one({'id': sku.id}))

    resp.status_code = 201
    resp.headers = {'Location': url_for('sku.sku_get', id=sku.id)}
    return resp

# api v2.0.0


@ sku.route('/api/sku/<id>', methods=['GET'])
def sku_get(id):
    detailed = request.args.get("details") == "true"

    sku = Sku.from_mongodb_doc(db.sku.find_one({"id": id}))
    if sku is None:
        return 'Sku does not exist.', 404
    return json.dumps(sku, cls=MyEncoder), 200

# api v2.0.0


@ sku.route('/api/sku/<id>', methods=['DELETE'])
def sku_delete(id):
    sku = Sku.from_mongodb_doc(db.sku.find_one({"id": id}))

    if sku is None:
        return 'Sku does not exist.', 404

    bins = db.bin.find({"contents.sku_id", sku.id})
    if not bins:
        return 'Must delete all instances of this SKU first.', 403

    db.sku.delete_one({"id": sku.id})
    return Response(status=200)
