from flask import Blueprint, request, Response, url_for
from inventory.data_models import Batch, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import admin_increment_code

import json

batch = Blueprint("batch", __name__)


@batch.route("/api/batches", methods=['POST'])
def batches_post():
    batch = Batch.from_json(request.json)
    resp = Response()
    existing = db.batch.find_one({"_id": batch.id})

    if not batch.id.startswith("BAT"):
        resp.status_code = 400
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "bad-id-format",
            "title": "Batch Ids must start with 'BAT'.",
            "invalid-params": [{
                "name": "id",
                "reason": "must start with 'BAT'"
            }]
        })
        return resp

    if existing:
        resp.status_code = 409
        resp.mimetype = "application/problem+json"
        resp.data = json.dumps({
            "type": "duplicate-resource",
            "title": "Cannot create duplicate batch.",
            "invalid-params": [{
                "name": "id",
                "reason": "must not be an existing batch id",
            }]})
        return resp

    admin_increment_code("BAT", batch.id)
    db.batch.insert_one(batch.to_mongodb_doc())

    resp.status_code = 201
    resp.location = url_for("batch.batch_get", id=batch.id)

    return resp


@batch.route("/api/batch/<id>", methods=["GET"])
def batch_get(id):
    pass
