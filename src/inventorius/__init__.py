# -*- coding: utf-8 -*-
"""
    inventorius
    ~~~~~~~~~~~~~~

    A flask app that implements the inventorius api.
    https://app.swaggerhub.com/apis-docs/computemachines/inventorius/3.1.0
"""

from flask import Flask, jsonify
# from flask import Flask, g, Response, url_for
# from flask import request, redirect
# import json
# import re
# import pprint
# from urllib.parse import urlencode

from inventorius.bin import bin
from inventorius.batch import batch
from inventorius.inventorius import inventorius
from inventorius.sku import sku
from inventorius.files import files
from inventorius.intake import intake
from inventorius.inventory_operations import inventory_operations
from inventorius.inventory_candidates import inventory_candidates
from inventorius.audit_snapshots import audit_snapshots
from inventorius.audit_observations import audit_observations
# from inventorius.data_models import Bin, MyEncoder, Uniq, Batch, Sku
from inventorius.auth import current_actor, init_auth
from inventorius.schema.routes import bp as schema_bp
from inventorius.process_definition import process_definition
from inventorius.util import no_cache
from inventorius.resource_models import StatusEndpoint

import platform
import os

sentry_dsn = False
try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_dsn = os.getenv("SENTRY_DSN")

    if sentry_dsn:
        print("setup sentry.io integration with configured sentry_dsn")
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],

            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for performance monitoring.
            # We recommend adjusting this value in production.
            traces_sample_rate=1.0
        )

except ModuleNotFoundError:
    print("error reporting disabled: 'python3-sentry-sdk' not installed")



app = Flask('inventorius')
BAD_REQUEST = ('Bad Request', 400)


app.register_blueprint(bin)
app.register_blueprint(batch)
app.register_blueprint(inventorius)
app.register_blueprint(sku)
app.register_blueprint(files)
app.register_blueprint(intake)
app.register_blueprint(inventory_operations)
app.register_blueprint(inventory_candidates)
app.register_blueprint(audit_snapshots)
app.register_blueprint(audit_observations)
app.register_blueprint(schema_bp)
app.register_blueprint(process_definition)
init_auth(app)

def cors_allow_all(response):
    if app.debug:
        # if platform.system() == "Linux":
        # warn if running on production server.
        # TODO: this is a little embarassing, but it will work for now
        print("!!! Using CORS - DEVELOPMENT ------------!!!------- DANGER ---------!!!---------- !!!")
        response.headers['Access-Control-Allow-Origin'] = 'http://localhost:8080'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,Idempotency-Key'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,PATCH,OPTIONS,DELETE'

    return response


app.after_request(cors_allow_all)


@app.route("/api", methods=["GET"], strict_slashes=False)
@no_cache
def api_root():
    """Return public navigation and caller-permitted application commands."""
    actor = current_actor()
    command_operations = []
    if actor.can("catalog.mutate"):
        command_operations.extend([
            {"rel": "create-bin", "method": "POST", "href": "/api/bins"},
            {"rel": "create-sku", "method": "POST", "href": "/api/skus"},
            {"rel": "create-batch", "method": "POST", "href": "/api/batches"},
            {
                "rel": "define-process",
                "method": "POST",
                "href": "/api/process-definitions",
            },
        ])
    if actor.can("inventory.mutate"):
        command_operations.extend([
            {"rel": "intake", "method": "POST", "href": "/api/intake"},
            {
                "rel": "inventory-operation",
                "method": "POST",
                "href": "/api/inventory-operations",
            },
            {
                "rel": "audit-observation",
                "method": "POST",
                "href": "/api/audit-observations",
            },
        ])
    if actor.can("schema.admin"):
        command_operations.append({
            "rel": "schema-admin",
            "method": "GET",
            "href": "/api/schema/list",
        })
    return jsonify({
        "Id": "/api",
        "state": {"service": "Inventorius"},
        "links": [
            {"rel": "search", "href": "/api/search"},
            {"rel": "inventory-activity", "href": "/api/inventory-operations"},
            {"rel": "authentication", "href": "/api/auth/session"},
        ],
        "operations": command_operations,
    })


@app.route("/api/status", methods=["GET"])
@no_cache
def get_version():
    from inventorius.db import db
    # Check database connectivity
    try:
        db.command("ping")
        db_connected = True
    except Exception:
        db_connected = False

    return StatusEndpoint(
        version="0.4.1",
        db_connected=db_connected,
        build_id=os.getenv("BUILD_ID", "dev")
    ).get_response()


@app.route("/api/stats", methods=["GET"])
@no_cache
def get_stats():
    from flask import Response, jsonify
    from inventorius.db import db

    try:
        bin_count = db.bin.estimated_document_count()
        sku_count = db.sku.estimated_document_count()
        batch_count = db.batch.estimated_document_count()

        # Get 5 most recent bins (by _id which has timestamp)
        recent_bins = list(db.bin.find({}, {"_id": 1, "props": 1}).sort("_id", -1).limit(5))
        recent_bins_list = [{"id": doc["_id"], "props": doc.get("props", {})} for doc in recent_bins]

        # Get 5 most recent SKUs
        recent_skus = list(db.sku.find({}, {"_id": 1, "name": 1}).sort("_id", -1).limit(5))
        recent_skus_list = [{"id": doc["_id"], "name": doc.get("name", "")} for doc in recent_skus]

        return jsonify({
            "counts": {
                "bins": bin_count,
                "skus": sku_count,
                "batches": batch_count,
            },
            "recent_bins": recent_bins_list,
            "recent_skus": recent_skus_list,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
