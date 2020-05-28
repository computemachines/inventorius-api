import itertools as it
import json
from flask import g, request_started
import pytest
from hypothesis import given, example, settings, note
import hypothesis.strategies as st
import tests.data_models_strategies as my_st

from inventory.app import app as inventory_flask_app
from inventory.app import get_mongo_client
from inventory.data_models import Bin, MyEncoder, Uniq, Batch, Sku

# give tests longer to complete on ci server
settings.register_profile("ci", deadline=500)
settings.load_profile("ci")

# from contextlib import contextmanager


def subscriber(sender):
    g.db = get_mongo_client().testing


request_started.connect(subscriber, inventory_flask_app)


def init_db():
    get_mongo_client().testing.bin.drop()
    get_mongo_client().testing.uniq.drop()
    get_mongo_client().testing.sku.drop()
    get_mongo_client().testing.batch.drop()


@pytest.fixture
def client():
    inventory_flask_app.testing = True
    init_db()
    yield inventory_flask_app.test_client()
    # close app


def test_empty_db(client):
    with client:
        resp = client.get("/api/bins")
        assert b"[]" == resp.data

        assert b"[]" == client.get("/api/bins").data

        assert g.db.bin.count_documents({}) == 0
        assert g.db.uniq.count_documents({}) == 0
        assert g.db.sku.count_documents({}) == 0
        assert g.db.batch.count_documents({}) == 0


@st.composite
def bins_(draw, id=None, props=None, contents=None):
    id = id or f"BIN{draw(st.integers(0, 10)):08d}"
    props = props or draw(my_st.json)
    return Bin(id=id, props=props)


@st.composite
def uniqs_(draw, id=None, bin_id=None):
    id = id or f"UNIQ{draw(st.integers(0, 10)):07d}"
    bin_id = bin_id or f"BIN{draw(st.integers(0, 10)):08d}"
    return Uniq(id=id, bin_id=bin_id)


@st.composite
def skus_(draw, id=None, owned_codes=None, name=None):
    id = id or f"SKU{draw(st.integers(0, 10)):08d}"
    owned_codes = owned_codes or draw(st.lists(st.text("abc")))
    name = draw(st.text("ABC"))
    return Sku(id=id, owned_codes=owned_codes, name=name)


@st.composite
def batches_(draw, id=None, sku_id=None):
    id = id or f"BAT{draw(st.integers(0, 10)):08d}"
    sku_id = sku_id or f"SKU{draw(st.integers(0, 100)):08d}"
    return Batch(id=id, sku_id=sku_id)


def post_bin(client, bin):
    return client.post("/api/bins", json=bin.to_json())


@given(bin=bins_())
@settings(max_examples=100)
def test_post_one_bin(client, bin):
    init_db()
    resp = post_bin(client, bin)
    assert resp.status_code == 201
    data = client.get("/api/bins").data
    assert json.loads(data) == json.loads(json.dumps([bin], cls=MyEncoder))


@given(bin1=st.one_of(bins_(id="BIN1") | bins_(id="BIN2")),
       bin2=st.one_of(bins_(id="BIN1") | bins_(id="BIN2")))
def test_post_two_bins(client, bin1, bin2):
    init_db()
    submitted_bins = []
    for bin in [bin1, bin2]:
        resp = post_bin(client, bin)
        if bin.id not in submitted_bins:
            assert resp.status_code == 201
            submitted_bins.append(bin.id)
        else:
            assert resp.status_code == 409


@given(bins=st.lists(bins_(), unique_by=lambda b: b.id))
def test_bins_pagination(client, bins):
    init_db()
    for bin in bins:
        resp = post_bin(client, bin)
        assert resp.status_code == 201

    all_data = []
    startingFrom = 0
    while startingFrom == 0 or all_data[-1] != []:
        note(all_data)
        resp = client.get("/api/bins", query_string={'limit': startingFrom+10,
                                                     'startingFrom': startingFrom})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data) <= 10

        startingFrom = startingFrom + 10
        all_data.append(data)

    flat_data = list(it.chain.from_iterable(all_data))
    assert flat_data == json.loads(json.dumps(bins, cls=MyEncoder))

# @given(bin=bins_())


@pytest.mark.skip()
@given(st.none(), st.none(), st.none())
@example(uniq1=Uniq(id="UNIQ1", bin_id="BIN1"),
         uniq2=Uniq(id="UNIQ2", bin_id="BIN1"),
         bin=Bin(id="BIN1"))
@example(uniq1=Uniq(id="UNIQ1", bin_id="BIN1"),
         uniq2=Uniq(id="UNIQ1", bin_id="BIN1"),
         bin=Bin(id="BIN1"))
def test_post_two_uniq(client, uniq1, uniq2, bin):
    if uniq1 is None:
        return
    init_db()
    client.post("/api/bins", json=bin.to_json())

    assert uniq1.bin_id == bin.id
    resp = client.post(f"/api/bin/{bin.id}/uniqs", json=uniq1.to_json())
    assert resp.status_code == 201

    resp = client.post(f"/api/bin/{bin.id}/uniqs", json=uniq2.to_json())
    if uniq2.id == uniq1.id:
        assert resp.status_code == 409  # uniq already exists
    if uniq2.id != uniq1.id and uniq2.bin_id != bin.id:
        assert resp.status_code == 404  # bin not found
    if uniq2.id != uniq1.id and uniq2.bin_id == bin.id:
        assert resp.status_code == 201  # uniq added


# avi v1.0.0 test
# @given(st.none(), st.none(), st.none())
# @example(sku1=Sku(id="SKU1", bin_id="BIN1"),
#          sku2=Sku(id="SKU2", bin_id="BIN1"),
#          bin=Bin(id="BIN1"))
# @example(sku1=Sku(id="SKU1", bin_id="BIN1"),
#          sku2=Sku(id="SKU2", bin_id="BIN2"),
#          bin=Bin(id="BIN1"))
# @example(sku1=Sku(id="SKU1", bin_id="BIN1"),
#          sku2=Sku(id="SKU1", bin_id="BIN2"),
#          bin=Bin(id="BIN1"))
# @example(sku1=Sku(id="SKU1", bin_id="BIN1"),
#          sku2=Sku(id="SKU1", bin_id="BIN1"),
#          bin=Bin(id="BIN1"))
# def test_post_sku(client, sku1, sku2, bin):
#     if sku1 is None: return
#     init_db()
#     client.post("/api/bins", json=bin.to_json())

#     assert sku1.bin_id == bin.id # sanity check
#     resp = client.post("/api/units/skus", json=sku1.to_json())
#     assert resp.status_code == 201

#     resp = client.post("/api/units/skus", json=sku2.to_json())
#     if sku2.id == sku1.id:
#         assert resp.status_code == 201 # sku count in bin increased
#     if sku2.id != sku1.id and sku2.bin_id != bin.id:
#         assert resp.status_code == 404 # bin not found
#     if sku2.id != sku1.id and sku2.bin_id == bin.id:
#         assert resp.status_code == 201 # sku  added

# @given(units=st.lists(strat_batches()))
# def test_post_batch(client, units):
#     init_db()
#     submitted_units = []
#     for unit in units:
#         resp = client.post("/api/units/batches", json=unit.to_json())
#         if unit.id not in submitted_units:
#             assert resp.status_code == 201
#             submitted_units.append(unit.id)
#         else:
#             assert resp.status_code == 409
