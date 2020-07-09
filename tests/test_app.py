import itertools as it
import json
from flask import g, request_started
import pytest
from hypothesis import given, example, settings
import hypothesis.strategies as st
import tests.data_models_strategies as my_st


from inventory.data_models import Bin, DataModelJSONEncoder as Encoder, Uniq, Batch, Sku


def test_empty_db(client):
    with client:
        resp = client.get("/api/bins")
        assert b"[]" == resp.data

        assert b"[]" == client.get("/api/bins").data

        assert g.db.bin.count_documents({}) == 0
        assert g.db.uniq.count_documents({}) == 0
        assert g.db.sku.count_documents({}) == 0
        assert g.db.batch.count_documents({}) == 0


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
