from flask import Blueprint, request, Response, url_for
from inventorius.db import db, fs
import json
from wand.image import Image

file_upload = Blueprint("file_upload", __name__)
 
@file_upload.route('/api/images', methods=['POST'])
def images_post():
  resp = Response()

  resp.status_code = 201

  if 'image' not in request.files:
    resp.status_code = 400
    resp.mimetype = "application/problem+json"
    resp.data = json.dumps({
        "type": "missing-request-data",
        "title": "Request is missing required key.",
        "invalid-params": [{
        "name": "image",
        "reason": "Input must be an image file."
    }]})
    return resp

  image = request.files['image']

  Image(blob=image.stream).save(filename='test.png')

  fs.put(b"hello worlds\n");
  return resp



# try:
#     assert_png(user_file)
#     with Image(filename='png:'+user_file) as img:
#         # ... do work ...
# except AssertionError:
#     # ... handle exception ...