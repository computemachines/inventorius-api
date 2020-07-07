from flask import Blueprint, request, Response
from inventory.data_models import Bin, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import get_body_type, admin_increment_code

import json

bins = Blueprint("bins", __name__)


@ bins.route('/api/bins', methods=['GET'])
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

    return json.dumps(bins, cls=Encoder)


def props_from_form(form):
    pass


# api v2.0.0
@bins.route('/api/bins', methods=['POST'])
def bins_post():
    bin_json = request.json
    bin = Bin.from_json(bin_json)
    admin_increment_code("BIN", bin.id)
    existing = db.bin.find_one({'_id': bin.id})

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


@ bins.route('/api/bin/<id>', methods=['GET'])
def bin_get(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"id": id}))
    if existing is None:
        return "The bin does not exist", 404
    else:
        return json.dumps(existing, cls=Encoder), 200

# api v2.0.0


@ bins.route('/api/bin/<id>', methods=['DELETE'])
def bin_delete(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"id": id}))
    if existing is None:
        return "The bin does not exist", 404
    if request.args.get('force', 'false') == 'true' or len(existing.contents) == 0:
        db.bin.delete_one({"id": id})
        return 'Bin was deleted along with all contents, if any.', 200
    else:
        return 'The bin is not empty and force was not set to true.', 403
