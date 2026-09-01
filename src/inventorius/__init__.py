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
import inventorius.resource_operations as resource_operation
from inventorius.inventorius import inventorius
from inventorius.sku import sku
from inventorius.files import files
from inventorius.intake import intake
from inventorius.inventory_operations import inventory_operations
from inventorius.inventory_candidates import inventory_candidates
from inventorius.audit_snapshots import audit_snapshots
from inventorius.audit_observations import audit_observations
from inventorius.quantity_routes import quantity_routes
from inventorius.constraint_query_routes import constraint_query_routes
# from inventorius.data_models import Bin, MyEncoder, Uniq, Batch, Sku
from inventorius.auth import current_actor, init_auth
from inventorius.schema.routes import bp as schema_bp
from inventorius.process_definition import process_definition
from inventorius.util import no_cache
from inventorius.resource_models import StatusEndpoint
from inventorius.release import metadata as release_metadata

import platform
import os

SENTRY_SDK = None


def scrub_sentry_event(event, _hint):
    """Retain failure provenance while dropping request/user-bearing context."""
    for key in ("request", "user", "contexts", "extra", "breadcrumbs"):
        event.pop(key, None)
    return event


def configure_sentry():
    """Configure error reporting without collecting user data or performance traces."""
    global SENTRY_SDK
    sentry_dsn = os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ModuleNotFoundError:
        print("error reporting disabled: 'sentry-sdk' not installed")
        return

    SENTRY_SDK = sentry_sdk
    build = release_metadata()
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration()],
        release=f"{build['component']}@{build['revision']}",
        environment=build["environment"],
        send_default_pii=False,
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        before_send=scrub_sentry_event,
    )


configure_sentry()



app = Flask('inventorius')
BAD_REQUEST = ('Bad Request', 400)


@app.before_request
def tag_sentry_release_context():
    """Attach deployment release state without changing immutable Sentry release."""
    if SENTRY_SDK is not None:
        SENTRY_SDK.set_tag("product_release", release_metadata()["product_release"])


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
app.register_blueprint(quantity_routes)
app.register_blueprint(constraint_query_routes)
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
            resource_operation.batch_create(rel="create-batch"),
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
            {
                "rel": "quantity-observation",
                "method": "POST",
                "href": "/api/quantity-observations",
            },
            {
                "rel": "quantity-withdrawal",
                "method": "POST",
                "href": "/api/quantity-withdrawals",
            },
        ])
    if actor.can("schema.admin"):
        command_operations.append({
            "rel": "schema-admin",
            "method": "GET",
            "href": "/api/schema/list",
        })
    if actor.can("solver.query"):
        command_operations.append({
            "rel": "solver-query",
            "method": "POST",
            "href": "/api/solver/query",
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

    build = release_metadata()
    return StatusEndpoint(
        version=build["component_version"],
        db_connected=db_connected,
        build_id=build["revision"],
        component=build["component"],
        revision=build["revision"],
        product_release=build["product_release"],
        environment=build["environment"],
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
