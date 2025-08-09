import contextlib
import sys
from pathlib import Path

import pytest
from hypothesis import settings

from flask import g, request_started

# Ensure the application package on the src/ path is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from inventorius import app as inventorius_flask_app
from inventorius.db import get_mongo_client


# give tests longer to complete on ci server
settings.register_profile("ci", deadline=500)
settings.load_profile("ci")

# from contextlib import contextmanager


def subscriber(sender):
    g.db = get_mongo_client().testing


request_started.connect(subscriber, inventorius_flask_app)


@pytest.fixture
def client():
    inventorius_flask_app.testing = True
    yield inventorius_flask_app.test_client()
    # close app


@contextlib.contextmanager
def clientContext():
    inventorius_flask_app.testing = True
    inventorius_flask_app.secret_key = "1234"
    test_db = get_mongo_client().testing
    test_db.admin.delete_many({})
    test_db.batch.delete_many({})
    test_db.bin.delete_many({})
    test_db.sku.delete_many({})
    test_db.user.delete_many({})
    yield inventorius_flask_app.test_client()
