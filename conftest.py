import contextlib
import pytest
from hypothesis import settings

from flask import g, request_started
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
    get_mongo_client().testing.admin.drop()
    get_mongo_client().testing.batch.drop()
    get_mongo_client().testing.bin.drop()
    get_mongo_client().testing.sku.drop()
    get_mongo_client().testing.user.drop()
    yield inventorius_flask_app.test_client()
