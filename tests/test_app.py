import pytest

from inventory.app import app as inventory_flask_app
from inventory.app import get_mongo_client, db
from inventory.data_models import Bin, MyEncoder

from contextlib import contextmanager
from flask import appcontext_pushed, g, request_started
import json

from .generators import *

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
    resp = client.get("/api/bins")
    assert b"[]" == resp.data

# def test_post_bins_new(client):
#     bin = generate_bin('BIN000012')
    
#     postResp = client.post("/api/bins", json=bin.toDict())
#     assert postResp.status_code == 201
#     assert postResp.headers.get('Location', None) is not None
    
#     resp = client.get("/api/bins")
#     respBins = [Bin(data) for data in json.loads(resp.data)]
#     assert respBins[0].toJson() == bin.toJson()
#     assert respBins == [bin]

# def test_post_bins_multiple_new(client):
#     bin1 = generate_bin('BIN000012')
#     bin2 = generate_bin('BIN000013')

#     postResp = client.post("/api/bins", json=bin1.toDict())
#     assert postResp.status_code == 201
#     assert postResp.headers.get('Location', None) is not None

#     postResp = client.post("/api/bins", json=bin2.toDict())
#     assert postResp.status_code == 201
#     assert postResp.headers.get('Location', None) is not None

#     resp = client.get("/api/bins")
#     respBins = [Bin(data) for data in json.loads(resp.data)]
#     assert respBins == [bin1, bin2] or respBins == [bin2, bin1]

# def test_post_bins_repeated(client):
#     bin = generate_bin('BIN000012')

#     postResp = client.post("/api/bins", json=bin.toDict())
#     assert postResp.status_code == 201
#     assert postResp.headers.get('Location', None) is not None

#     postResp = client.post("/api/bins", json=bin.toDict())
#     assert postResp.status_code == 409 # Bin should already exist
#     assert postResp.headers.get('Location', None) is not None

#     resp = client.get("/api/bins")
#     respBins = [Bin(data) for data in json.loads(resp.data)]
#     assert respBins == [bin]

# def test_get_bin(client):
#     bin = generate_bin('BIN000012')
    
#     postResp = client.post("/api/bins", json=bin.toDict())
#     assert postResp.status_code == 201
#     resource = postResp.headers.get('Location', None)
    
#     resp = client.get(resource)
#     respBin = Bin(json.loads(resp.data))
#     assert respBin == bin

