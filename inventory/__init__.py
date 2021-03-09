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

# from inventory.data_models import Bin, MyEncoder, Uniq, Batch, Sku

app = Flask('inventory')
BAD_REQUEST = ('Bad Request', 400)

app.register_blueprint(bin)
app.register_blueprint(batch)
app.register_blueprint(inventory)
app.register_blueprint(sku)


@app.route("/api/version", methods=["GET"])
def get_version():
    return "0.1.4"
