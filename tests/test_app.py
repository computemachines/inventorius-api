import pytest
from hypothesis import given, example
import hypothesis.strategies as strat
import tests.data_models_strategies as my_strat

from inventory.app import app as inventory_flask_app
from inventory.app import get_mongo_client, db
from inventory.data_models import Bin, MyEncoder

from contextlib import contextmanager
from flask import appcontext_pushed, g, request_started
import json

def subscriber(sender):
    g.db = get_mongo_client().testing
request_started.connect(subscriber, inventory_flask_app)

def init_db():
    get_mongo_client().testing.bins.drop()
    
@pytest.fixture
def client():
    inventory_flask_app.testing = True
    inventory_flask_app.config['LOCAL_MONGO'] = True
    init_db()
    yield inventory_flask_app.test_client()
    #close app


def test_empty_db(client):
    with client:
        resp = client.get("/api/bins")
        assert g.db.bins.count() == 0

        assert b"[]" == resp.data

@strat.composite
def strat_bins(draw):
    id = f"BIN{draw(strat.integers()):08d}"
    props = draw(my_strat.json)
    contents = draw(strat.just([]) | strat.none())
    return Bin(id=id, props=props, contents=contents)

@given(bin=strat_bins())
def test_post_bin(client, bin):
    init_db()
    with client:
        resp = client.post("/api/bins", json=bin.to_json())
        
    assert resp.status_code == 201

@pytest.mark.skip()
@given(bins=strat.lists(strat_bins()))
def test_post_bins(client, bins):
    for bin in bins:
        resp = client.post("/api/bins", json=bin.to_json())
        if bin.id in [b.id for b in bins]:
            assert resp.status_code == 409
        else:
            assert resp.status_code == 201
    resp = client.get("/api/bins")

    
    
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

