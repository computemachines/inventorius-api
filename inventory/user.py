from flask import Blueprint, request, Response, url_for, session
from inventory.data_models import Batch, Bin, Sku, DataModelJSONEncoder as Encoder
from inventory.db import db
from inventory.util import admin_increment_code, check_code_list


user = Blueprint("user", __name__)

@user.route("/api/memo", methods=["GET"])
def memo_get():
  return session['memo']

@user.route("/api/memo", methods=["POST"])
def memo_put():
  print(request.form)
  print(request.json)
  session['memo'] = request.form['memo']
  return Response(status=201)