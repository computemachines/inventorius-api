# -*- coding: utf-8 -*-
"""
    inventory
    ~~~~~~~~~~~~~~

    A flask app that implements the inventory api.
    https://app.swaggerhub.com/apis-docs/computemachines/Inventory/3.1.0
"""

from flask import Flask
# from flask import Flask, g, Response, url_for
# from flask import request, redirect
# import json
# import re
# import pprint
# from urllib.parse import urlencode

from inventory.bin import bin
from inventory.batch import batch
from inventory.inventory import inventory
from inventory.sku import sku
# from inventory.file_upload import file_upload
# from inventory.data_models import Bin, MyEncoder, Uniq, Batch, Sku
from inventory.user import user
from inventory.util import login_manager, principals

import os
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration


sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    print("setup sentry.io integration")
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration()],

        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=1.0
    )


app = Flask('inventory')
BAD_REQUEST = ('Bad Request', 400)


app.register_blueprint(bin)
app.register_blueprint(batch)
app.register_blueprint(inventory)
app.register_blueprint(sku)
# app.register_blueprint(file_upload)
app.register_blueprint(user)

if app.debug:
    print("!!! ENVIROMENT SETTING SECRET KEY FOR SESSIONS !!!")
    app.secret_key = os.getenv("FLASK_SECRET_KEY")


def cors_allow_all(response):
    # if app.debug:
        # print("!!! Using CORS - DEVELOPMENT ------------!!!------- DANGER ---------!!!---------- !!!")
        # response.headers['Access-Control-Allow-Origin'] = 'http://localhost:8080'
        # response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        # response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,PATCH,OPTIONS,DELETE'

    return response


app.after_request(cors_allow_all)
login_manager.init_app(app)
principals.init_app(app)

@app.route("/api/version", methods=["GET"])
def get_version():
    return "0.2.15-0"

@app.route('/api/debug-sentry')
def trigger_error():
    division_by_zero = 1 / 0