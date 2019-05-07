import pytest
from hypothesis import given, example
import hypothesis.strategies as strat
import tests.data_models_strategies as my_strat

from inventory.app import app as inventory_flask_app
from inventory.app import get_mongo_client, db
from inventory.data_models import Bin, MyEncoder, Uniq, Batch, Sku

from contextlib import contextmanager
from flask import appcontext_pushed, g, request_started
import json

def subscriber(sender):
    g.db = get_mongo_client().testing
request_started.connect(subscriber, inventory_flask_app)

def init_db():
    get_mongo_client().testing.bins.drop()
    get_mongo_client().testing.uniq.drop()
    get_mongo_client().testing.sku.drop()
    get_mongo_client().testing.batch.drop()

    
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
        assert b"[]" == resp.data

        assert b"[]" == client.get("/api/units").data

        assert g.db.bins.count_documents({}) == 0
        assert g.db.uniq.count_documents({}) == 0
        assert g.db.sku.count_documents({}) == 0
        assert g.db.batch.count_documents({}) == 0

@strat.composite
def strat_bins(draw, id=None):
    id = id or f"BIN{draw(strat.integers(0)):08d}"
    props = draw(my_strat.json)
    contents = draw(strat.just([]) | strat.none())
    return Bin(id=id, props=props, contents=contents)

@strat.composite
def strat_uniqs(draw, id=None, bin_id=None):
    id = id or f"UNIQ{draw(strat.integers(0)):07d}"
    bin_id = bin_id or f"BIN{draw(strat.integers(0)):08d}"
    return Uniq(id=id, bin_id=bin_id)

@strat.composite
def strat_skus(draw, id=None, owned_codes=None, name=None):
    id = id or f"SKU{draw(strat.integers(0)):08d}"
    owned_codes = owned_codes or draw(strat.lists(strat.text()))
    name = draw(strat.text())
    return Sku(id=id, owned_codes=owned_codes, name=name)

@strat.composite
def strat_batchs(draw, id=None, sku_id=None):
    id = id or f"BAT{draw(strat.integers(0)):08d}"
    sku_id = sku_id or f"SKU{draw(strat.integers(0)):08d}"
    return Batch(id=id, sku_id=sku_id)

@given(units=strat.lists(strat_uniqs()))
def test_post_uniq(client, units):
    init_db()
    submitted_units = []
    for unit in units:
        resp = client.post("/api/units/uniqs", json=unit.to_json())
        if unit.id not in submitted_units:
            assert resp.status_code == 201
            submitted_units.append(unit.id)
        else:
            assert resp.status_code == 409

@pytest.mark.skip()
@given(units=strat.lists(strat_skus()))
def test_post_sku(client, units):
    init_db()
    with client:
        resp = client.post("/api/units/skus", json=unit.to_json())
    assert resp.status_code == 201

@pytest.mark.skip()
@given(units=strat.lists(strat_batchs()))
def test_post_batch(client, units):
    init_db()
    with client:
        resp = client.post("/api/units/batchs", json=unit.to_json())
    assert resp.status_code == 201

@pytest.mark.skip() # delete soon
@given(bin=strat_bins())
def test_post_bin(client, bin):
    init_db()
    resp = client.post("/api/bins", json=bin.to_json())
    assert resp.status_code == 201


@pytest.mark.skip()
@given(bins=strat.lists(strat_bins()))
def test_post_bins(client, bins):
    init_db()
    print(len(bins))
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

