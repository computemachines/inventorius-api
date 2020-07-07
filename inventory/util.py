from flask import request
import re

from inventory.db import db


def getIntArgs(args, name, default):
    str_value = args.get(name, default)
    try:
        value = int(str_value)
    except ValueError:
        value = default
    return value


def get_body_type():
    if request.mimetype == 'application/json':
        return 'json'
    if request.mimetype in ('application/x-www-form-urlencoded',
                            'multipart/form-data'):
        return 'form'


def owned_code_get(id):
    existing = Sku.from_mongodb_doc(
        db.sku.find_one({'owned_codes': id}))
    return existing


def admin_increment_code(prefix, code):
    code_number = int(re.sub('[^0-9]', '', code))
    next_unused = int(re.sub('[^0-9]', '', admin_get_next(prefix)))

    if code_number >= next_unused:
        max_code = code_number
        if prefix == "SKU":
            db.admin.replace_one({"_id": "SKU"}, {"_id": "SKU",
                                                  "next": f"SKU{max_code+1:06}"})
        if prefix == "UNIQ":
            db.admin.replace_one({"_id": "UNIQ"}, {"_id": "UNIQ",
                                                   "next": f"UNIQ{max_code+1:05}"})
        if prefix == "BATCH":
            db.admin.replace_one({"_id": "BATCH"}, {"_id": "BATCH",
                                                    "next": f"BATCH{max_code+1:04}"})
        if prefix == "BIN":
            db.admin.replace_one({"_id": "BIN"}, {"_id": "BIN",
                                                  "next": f"BIN{max_code+1:06}"})


def admin_get_next(prefix):

    def max_code_value(collection, prefix):
        cursor = collection.find()
        max_value = 0
        for doc in cursor:
            code_number = int(doc['id'].strip(prefix))
            if code_number > max_value:
                max_value = code_number
        return max_value

    next_code_doc = db.admin.find_one({"_id": prefix})
    if not next_code_doc:
        if prefix == "SKU":
            max_value = max_code_value(db.sku, "SKU")
            db.admin.insert_one({"_id": "SKU",
                                 "next": f"SKU{max_value+1:06}"})
        if prefix == "UNIQ":
            max_value = max_code_value(db.uniq, "UNIQ")
            db.admin.insert_one({"_id": "UNIQ",
                                 "next": f"UNIQ{max_value+1:05}"})
        if prefix == "BATCH":
            max_value = max_code_value(db.batch, "BATCH")
            db.admin.insert_one({"_id": "BATCH",
                                 "next": f"BATCH{max_value+1:04}"})
        if prefix == "BIN":
            max_value = max_code_value(db.bin, "BIN")
            db.admin.insert_one({"_id": "BIN",
                                 "next": f"BIN{max_value+1:06}"})
        next_code_doc = db.admin.find_one({"_id": prefix})
    return next_code_doc['next']
