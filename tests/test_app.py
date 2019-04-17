import pytest

from inventory.app import app as inventory_flask_app
from inventory.app import get_mongo_client, db
from inventory.helpers import Bin, MyEncoder

from contextlib import contextmanager
from flask import appcontext_pushed, g, request_started
import json

def subscriber(sender):
    g.db = get_mongo_client().testing
request_started.connect(subscriber, inventory_flask_app)

def init_db(db):
    db.bins.drop()

@pytest.fixture
def client():
    inventory_flask_app.testing = True
    inventory_flask_app.config['LOCAL_MONGO'] = True
    init_db(get_mongo_client().testing)
    yield inventory_flask_app.test_client()
    #close app

def test_empty_db(client):
    # assert False
    resp = client.get("/api/bins")
    assert b"[]" == resp.data
    # assert False

def test_post_bins_new(client):
    bin = Bin({
        "id": "BIN000012",
        "props": {
            "bin dimensions": [
                "100mm",
                "200mm",
                "60mm"
            ],
            "process": "Receive"
        }})
    
    postResp = client.post("/api/bins", json=bin.toDict())
    assert postResp.status_code == 201
    assert postResp.headers.get('Location', None) is not None
    print(postResp.headers)
    
    resp = client.get("/api/bins")
    respBins = [Bin(data) for data in json.loads(resp.data)]
    assert respBins[0].toJson() == bin.toJson()
    assert respBins == [bin]
