from flask import g
from pymongo import MongoClient, TEXT
from werkzeug.local import LocalProxy
from gridfs import GridFS

# memoize mongo_client
_mongo_client = None


def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        db_host = "localhost"
        _mongo_client = MongoClient(db_host, 27017)
        _mongo_client.inventoriusdb.sku.create_index([('name', TEXT)])
        _mongo_client.inventoriusdb.batch.create_index([('name', TEXT)])
        _mongo_client.inventoriusdb.user.create_index([('name', TEXT)])

    return _mongo_client


def get_db():
    if 'db' not in g:
        g.db = get_mongo_client().inventoriusdb
    return g.db

def get_gridfs_db():
    if 'fs' not in g:
        g.fs = GridFS(get_mongo_client().gridfsdb)
    return g.fs

db = LocalProxy(get_db)
fs = LocalProxy(get_gridfs_db)