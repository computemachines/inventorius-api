from flask import Blueprint, request, Response
from inventory.data_models import Bin, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import get_body_type, admin_increment_code

import json

bins = Blueprint("bins", __name__)


@bins.route('/api/bins', methods=['POST'])
def bins_post():
    bin_json = request.json
    bin = Bin.from_json(bin_json)
    admin_increment_code("BIN", bin.id)
    existing = db.bin.find_one({'_id': bin.id})

    resp = Response()

    if not bin.id.startswith('BIN'):
        resp.status_code = 400
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "bad-id-format",
            "title": "Bin Ids must start with 'BIN'.",
            "invalid-params": [{
                "name": "id",
                "reason": "must start with string 'BIN'"
            }]})
        return resp

    if existing:
        resp.status_code = 409
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "duplicate-bin",
            "title": "Cannot create duplicate bin.",
            "invalid-params": [{
                "name": "id",
                "reason": "must not be an existing bin id"
            }]})
        return resp

    db.bin.insert_one(bin.to_mongodb_doc())
    resp.status_code = 201
    resp.data = bin.to_json()
    return resp

# api v2.0.0


@ bins.route('/api/bin/<id>', methods=['GET'])
def bin_get(id):
    print(id)
    existing = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    if existing is None:
        return "The bin does not exist", 404
    else:
        return {
            "state": json.loads(existing.to_json())
        }

# api v2.0.0


@ bins.route('/api/bin/<id>', methods=['DELETE'])
def bin_delete(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    if existing is None:
        return "The bin does not exist", 404
    if request.args.get('force', 'false') == 'true' or len(existing.contents) == 0:
        db.bin.delete_one({"id": id})
        return 'Bin was deleted along with all contents, if any.', 200
    else:
        return 'The bin is not empty and force was not set to true.', 403
