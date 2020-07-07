from hypothesis import given, settings, note
from hypothesis.strategies import one_of, lists
import json
import itertools as it

from tests.data_models_strategies import bins_

from inventory.db import init_db
from inventory.data_models import DataModelJSONEncoder as Encoder


def post_bin(client, bin):
    return client.post("/api/bins", json=bin.to_json())


@given(bin=bins_())
@settings(max_examples=100)
def test_post_one_bin(client, bin):
    init_db()
    resp = post_bin(client, bin)
    assert resp.status_code == 201
    data = client.get("/api/bins").data
    assert json.loads(data) == json.loads(json.dumps([bin], cls=Encoder))


@given(bin1=one_of(bins_(id="BIN1") | bins_(id="BIN2")),
       bin2=one_of(bins_(id="BIN1") | bins_(id="BIN2")))
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


@given(bins=lists(bins_(), unique_by=lambda b: b.id))
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
    assert flat_data == json.loads(json.dumps(bins, cls=Encoder))

# @given(bin=bins_())
