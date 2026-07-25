import os

from flask import g
from gridfs import GridFS
from pymongo import ASCENDING, TEXT, MongoClient
from werkzeug.local import LocalProxy

# memoize mongo_client
_mongo_client = None


def get_mongo_client():
    global _mongo_client
    if _mongo_client is None:
        mongo_uri = os.getenv("INVENTORIUS_MONGO_URI")
        if mongo_uri:
            _mongo_client = MongoClient(mongo_uri)
        else:
            db_host = os.getenv("INVENTORIUS_MONGO_HOST", "localhost")
            db_port = int(os.getenv("INVENTORIUS_MONGO_PORT", "27017"))
            _mongo_client = MongoClient(db_host, db_port)
        _mongo_client.inventoriusdb.sku.create_index([("name", TEXT)])
        _mongo_client.inventoriusdb.batch.create_index([("name", TEXT)])
        for collection_name in (
            "auth_bootstrap_tokens",
            "auth_challenges",
            "auth_sessions",
        ):
            _mongo_client.inventoriusdb[collection_name].create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="expires_at_ttl",
            )
        _mongo_client.inventoriusdb.auth_credentials.create_index(
            [("principal_id", ASCENDING)],
            name="credentials_by_principal",
        )
        _mongo_client.inventoriusdb.auth_recovery_codes.create_index(
            [("principal_id", ASCENDING)],
            name="recovery_codes_by_principal",
        )
        # Source-aware inventory resolution has a different access path from
        # the batch-first holding identity index used by ledger projection.
        _mongo_client.inventoriusdb.inventory_holdings.create_index(
            [
                ("location_id", ASCENDING),
                ("unit", ASCENDING),
                ("packaging_configuration_id", ASCENDING),
                ("batch_id", ASCENDING),
            ],
            name="inventory_candidates_by_source",
        )
        _mongo_client.inventoriusdb.batch.create_index(
            [("sku_id", ASCENDING)], name="batch_by_sku"
        )
        for collection_name in ("sku", "batch"):
            collection = _mongo_client.inventoriusdb[collection_name]
            for relationship in ("owned", "associated"):
                collection.create_index(
                    [(f"{relationship}_codes", ASCENDING)],
                    name=f"{collection_name}_{relationship}_codes",
                )

    return _mongo_client


def get_db():
    if "db" not in g:
        g.db = get_mongo_client().inventoriusdb
    return g.db


def get_gridfs_db():
    if "fs" not in g:
        g.fs = GridFS(get_mongo_client().gridfsdb)
    return g.fs


db = LocalProxy(get_db)
fs = LocalProxy(get_gridfs_db)
