# -*- coding: utf-8 -*-
"""
    inventorius
    ~~~~~~~~~~~~~~

    A flask app that implements the inventorius api.
    https://app.swaggerhub.com/apis-docs/computemachines/inventorius/3.1.0
"""

from flask import Flask
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
# from inventorius.file_upload import file_upload
# from inventorius.data_models import Bin, MyEncoder, Uniq, Batch, Sku
from inventorius.user import user
from inventorius.util import login_manager, no_cache, principals
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
# app.register_blueprint(file_upload)
app.register_blueprint(user)

if app.debug:
    print("!!! ENVIROMENT SETTING SECRET KEY FOR SESSIONS !!!")
    app.secret_key = os.getenv("FLASK_SECRET_KEY")


def cors_allow_all(response):
    if app.debug:
        # if platform.system() == "Linux":
        # warn if running on production server.
        # TODO: this is a little embarassing, but it will work for now
        print("!!! Using CORS - DEVELOPMENT ------------!!!------- DANGER ---------!!!---------- !!!")
        response.headers['Access-Control-Allow-Origin'] = 'http://localhost:8080'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,PATCH,OPTIONS,DELETE'

    return response


app.after_request(cors_allow_all)
login_manager.init_app(app)
principals.init_app(app)


@app.route("/api/status", methods=["GET"])
@no_cache
def get_version():
    return StatusEndpoint(
        version="0.3.11"
    ).get_response()
