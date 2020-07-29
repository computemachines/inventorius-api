from flask import Blueprint, request, Response, url_for
from inventory.data_models import Sku, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import admin_increment_code

import json

sku = Blueprint("sku", __name__)


@ sku.route('/api/skus', methods=['POST'])
def skus_post():
    sku = Sku.from_json(request.json)

# copied from ./bins.py
    # resp = Response()

    # if not bin.id.startswith('BIN'):
    #     resp.status_code = 400
    #     resp.mimetype = "application/problem+json"
    #     resp.data = json.dumps({
    #         "type": "bad-id-format",
    #         "title": "Bin Ids must start with 'BIN'.",
    #         "invalid-params": [{
    #             "name": "id",
    #             "reason": "must start with string 'BIN'"
    #         }]})
    #     return resp

    if db.sku.find_one({'id': sku.id}):
        return Response(status=409, headers={
            'Location': url_for('sku.sku_get', id=sku.id)})

    admin_increment_code("SKU", sku.id)
    db.sku.insert_one(sku.to_mongodb_doc())
    dbSku = Sku.from_mongodb_doc(db.sku.find_one({'id': sku.id}))
    return Response(json.dumps(dbSku, cls=Encoder), status=200, headers={
        'Location': url_for('sku.sku_get', id=sku.id)})

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
