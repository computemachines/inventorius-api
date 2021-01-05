from flask import Blueprint, request, Response, url_for
from inventory.data_models import Bin, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import get_body_type, admin_increment_code

import json

bin = Blueprint("bin", __name__)


@bin.route('/api/bins', methods=['POST'])
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
                "reason": "must start with 'BIN'"
            }]})
        return resp

    if existing:
        resp.status_code = 409
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "duplicate-resource",
            "title": "Cannot create duplicate bin.",
            "invalid-params": [{
                "name": "id",
                "reason": "must not be an existing bin id",
            }]})
        resp.headers["Location"] = url_for("bin.bin_get", id=bin.id)
        return resp

    db.bin.insert_one(bin.to_mongodb_doc())
    resp.status_code = 201
    resp.mimetype = "application/json"
    resp.data = bin.to_json()
    return resp

# api v2.0.0


@bin.route('/api/bin/<id>', methods=['GET'])
def bin_get(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    if existing is None:
        resp = Response()
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "The requested bin does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an existing bin id"
            }]
        })
        return resp

    else:
        return {
            "state": json.loads(existing.to_json())
        }


@bin.route('/api/bin/<id>', methods=['PATCH'])
def bin_patch(id):
    patch = request.json
    existing = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    resp = Response()

    if existing is None:
        resp.status_code = 404
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "The requested bin does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an existing bin id"
            }]
        })
        return resp

    if "props" in patch.keys():
        db.bin.update_one({"_id": id},
                          {"$set": {"props": patch['props']}})

    return Response(status=200, headers={"Cache-Control": "no-cache"})


@bin.route('/api/bin/<id>', methods=['DELETE'])
def bin_delete(id):
    existing = Bin.from_mongodb_doc(db.bin.find_one({"_id": id}))
    resp = Response()
    if existing is None:
        resp.status_code = 404
        resp.headers = {"Cache-Control": "no-cache"}
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "missing-resource",
            "title": "Can not delete bin that does not exist.",
            "invalid-params": [{
                "name": "id",
                "reason": "must be an exisiting bin id"
            }]
        })
        return resp
    if request.args.get('force', 'false') == 'true' or len(existing.contents) == 0:
        db.bin.delete_one({"_id": id})
        return Response(status=204, headers={"Cache-Control": "no-cache"})
    else:
        return 'The bin is not empty and force was not set to true.', 403
