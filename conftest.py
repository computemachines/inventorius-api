import contextlib
import pytest
from hypothesis import settings

from flask import g, request_started
from inventory import app as inventory_flask_app
from inventory.db import get_mongo_client, init_db


# give tests longer to complete on ci server
settings.register_profile("ci", deadline=500)
settings.load_profile("ci")

# from contextlib import contextmanager


def subscriber(sender):
    g.db = get_mongo_client().testing


request_started.connect(subscriber, inventory_flask_app)


@pytest.fixture
def client():
    inventory_flask_app.testing = True
    init_db()
    yield inventory_flask_app.test_client()
    # close app


@contextlib.contextmanager
def clientContext():
    inventory_flask_app.testing = True
    init_db()
    yield inventory_flask_app.test_client()
