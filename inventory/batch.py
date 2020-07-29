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

    if not batch.id.startswith("BAT"):
        resp.status_code = 409
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

    admin_increment_code("BAT", batch.id)
    db.batches.insert_one(batch.to_mongodb_doc())

    resp.status_code = 201
    resp.location = url_for("batch.batch_get", id=batch.id)

    return resp
