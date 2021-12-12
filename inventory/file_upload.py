from flask import Blueprint, request, Response, url_for
from inventory.db import db
import json

file_upload = Blueprint("file_upload", __name__)

@file_upload.route('/api/images', methods=['POST'])
def images_post():
  resp = Response()

  resp.status_code = 301
  resp.data = json.dumps(list(request.files.keys()))

  image = request.files['image']

  return resp