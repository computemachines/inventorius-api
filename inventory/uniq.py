from flask import Blueprint, request, url_for
from inventory.data_models import Uniq, DataModelJSONEncoder as Encoder
from inventory.db import db

import json

uniq = Blueprint("uniq", __name__)


@ uniq.route('/api/uniqs', methods=['POST'])
def uniqs_post():
    if get_body_type() == 'json':
        uniq_json = request.json.copy()
    elif get_body_type() == 'form':
        uniq_json = {
            'id': request.form['uniq_id'],
            'bin_id': request.form['bin_id'],
            'owned_codes': request.form['owned_codes'].split(),
            'sku_parent': request.form.get('sku_id', None),
            'name': request.form.get('uniq_name', None)
        }
    uniq = Uniq.from_json(uniq_json)
    bin_id = uniq_json['bin_id']
    bin = Bin.from_mongodb_doc(db.bin.find_one({"id": bin_id}))

    if bin is None:
        return Response("Bin not found", status=404, headers={
            'Location': url_for('bin.bin_get', id=bin_id)})
    if db.uniq.find_one({"id": uniq.id}):
        return Response("Uniq not found", status=409, headers={
            'Location': url_for('uniq.uniq_get', id=uniq.id)})

    admin_increment_code("UNIQ", uniq.id)
    db.uniq.insert_one(uniq.to_mongodb_doc())
    db.bin.update_one(
        {"id": bin.id},
        {"$push": {"contents": {"uniq_id": uniq.id, "quantity": 1}}})
    print(f"/uniq/{uniq.id}")
    resp = Response(status=201, headers={
        'Location': f"/uniq/{uniq.id}"})
    if get_body_type() == 'form' and resp.status_code == 201:
        resp.status_code = 302
    return resp


@ uniq.route('/api/uniq/<id>', methods=['GET'])
def uniq_get(id):
    uniq = Uniq.from_mongodb_doc(db.uniq.find_one({"id": id}))
    if not uniq:
        return Response(status=404)
    return uniq.to_json(), 200

# api v2.0.0


@ uniq.route('/api/uniq/<id>', methods=['DELETE'])
def uniq_delete(id):
    uniq = Uniq.from_mongodb_doc(db.uniq.find_one({"id": id}))
    if not uniq:
        return 'The unit does not exist so can not be deleted.', 404

    db.uniq.delete_one({"id": uniq.id})
    db.bin.update_one({"contents.uniq_id": uniq.id},
                      {"$pull": {"uniq_id": uniq.id}})
    return Response(status=200)
