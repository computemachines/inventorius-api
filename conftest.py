import contextlib
import os
import sys
from pathlib import Path

import pytest
from hypothesis import settings

from flask import g, request_started

# Ensure the application package on the src/ path is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
# The local Mongo replica set advertises its Compose hostname (``mongo``),
# which a host pytest process cannot resolve.  Direct connection keeps local
# tests on the published port; CI or another caller can still supply its own
# explicit URI.
os.environ.setdefault(
    "INVENTORIUS_MONGO_URI",
    "mongodb://localhost:27017/?replicaSet=inventorius-rs&directConnection=true",
)
from inventorius import app as inventorius_flask_app
from inventorius.db import get_mongo_client
from tests.database import get_test_database


# These integration/property tests exercise a real MongoDB database. Their
# correctness is not time-dependent, and machine or disk load makes per-example
# deadlines inherently flaky.
settings.register_profile("ci", deadline=None)
settings.load_profile("ci")

# from contextlib import contextmanager


def subscriber(sender):
    g.db = get_test_database()


request_started.connect(subscriber, inventorius_flask_app)


@pytest.fixture
def client():
    inventorius_flask_app.testing = True
    yield inventorius_flask_app.test_client()
    # close app


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database():
    """Start clean and remove this pytest process's private database."""
    database = get_test_database()
    get_mongo_client().drop_database(database.name)
    yield
    get_mongo_client().drop_database(database.name)


@contextlib.contextmanager
def clientContext():
    inventorius_flask_app.testing = True
    inventorius_flask_app.secret_key = "1234"
    test_db = get_test_database()
    test_db.admin.delete_many({})
    test_db.batch.delete_many({})
    test_db.bin.delete_many({})
    test_db.inventory_code_observations.delete_many({})
    test_db.inventory_counters.delete_many({})
    test_db.inventory_holdings.delete_many({})
    test_db.inventory_operations.delete_many({})
    test_db.sku.delete_many({})
    test_db.user.delete_many({})
    yield inventorius_flask_app.test_client()
