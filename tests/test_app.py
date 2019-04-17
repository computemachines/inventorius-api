import os
import sys
import tempfile

import pytest

print(sys.path)

from inventory.app import app as inventory_flask_app
# inventory_flask_app  = inventory.app.app
from inventory.app import get_mongo_client, db

from contextlib import contextmanager
from flask import appcontext_pushed, g, request_started

def subscriber(sender):
    g.db = get_mongo_client().testing
    print("localproxy db: {}".format(db))
    
request_started.connect(subscriber, inventory_flask_app)

@pytest.fixture
def client():
    inventory_flask_app.testing = True
    inventory_flask_app.config['LOCAL_MONGO'] = True
    yield inventory_flask_app.test_client()
    #close app

def test_empty_db(client):
    # assert False
    resp = client.get("/api/bins")
    print(resp.data)
    assert b"[]" == resp.data
    print("DONE")
    # assert False
