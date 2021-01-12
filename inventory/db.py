from flask import g
from pymongo import MongoClient, TEXT
from werkzeug.local import LocalProxy

# memoize mongo_client
_mongo_client = None


def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        db_host = "localhost"
        _mongo_client = MongoClient(db_host, 27017)
        _mongo_client.inventorydb.sku.create_index([('name', TEXT)])
        _mongo_client.inventorydb.batch.create_index([('name', TEXT)])

    return _mongo_client


def get_db():
    if 'db' not in g:
        g.db = get_mongo_client().inventorydb
    return g.db


db = LocalProxy(get_db)
