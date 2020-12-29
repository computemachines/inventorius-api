from conftest import clientContext
import pytest
import hypothesis.strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, initialize, invariant, multiple
from inventory.data_models import Bin, Sku, Batch
import tests.data_models_strategies as dst

bin1 = Bin(id="BIN1")
bin2 = Bin(id="BIN2")
sku1 = Sku(id="SKU1")


def test_move(client):
    client.post('/api/bins', json=bin1.to_json())
    client.post('/api/bins', json=bin2.to_json())
    client.post('/api/skus', json=sku1.to_json())
    client.post('/api/receive', json={
        "bin_id": bin1.id,
        "sku_id": sku1.id,
        "quantity": 2
    })
    client.post('/api/move', json={
        "sku": sku1.id,
        "from": bin1.id,
        "to": bin2.id,
        "count": 1})
    rp = client.get('/api/bin/BIN1')
    assert rp.status_code == 200
    assert rp.is_json
    assert rp.json['state']['contents'][0]['id'] == sku1.id
    assert rp.json['state']['contents'][0]['quantity'] == 1


class InventoryStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super(InventoryStateMachine, self).__init__()
        with clientContext() as client:
            self.client = client
            self.bins = {}
            self.skus = {}
            self.batches = {}

    binIds = Bundle("binIds")
    skuIds = Bundle("skuIds")
    batchIds = Bundle("batchIds")

    @rule(target=skuIds, sku=dst.skus_())
    def add_sku(self, sku):
        resp = self.client.post('/api/skus', json=sku.to_json())
        if sku.id in self.skus.keys():
            assert resp.status_code == 409
            assert resp.is_json
            return multiple()
        else:
            assert resp.status_code == 201
            self.skus[sku.id] = sku
            return sku.id

    @rule(target=binIds, bin=dst.bins_())
    def add_bin(self, bin):
        resp = self.client.post('/api/bins', json=bin.to_json())
        if bin.id in self.bins.keys():
            assert resp.status_code == 409
            assert resp.is_json
            assert resp.json['type'] == 'duplicate-resource'
            return multiple()
        else:
            assert resp.status_code == 201
            self.bins[bin.id] = bin
            return bin.id

    @rule(target=batchIds, batch=dst.batches_())
    def add_batch(self, batch):
        resp = self.client.post('/api/batches', json=batch.to_json())
        if batch.id in self.batches.keys():
            assert resp.status_code == 409
            assert resp.is_json
        else:
            assert resp.status_code == 201
            self.batches[batch.id] = batch
            return batch.id

    @rule(binId=binIds)
    def get_bin(self, binId):
        rp = self.client.get(f'/api/bin/{binId}')
        assert rp.is_json
        assert self.bins[binId].props == rp.json['state']['props']


TestInventory = InventoryStateMachine.TestCase


def test_repeat_sku_push():
    state = InventoryStateMachine()
    v1 = state.add_sku(sku=Sku(associated_codes=[],
                               id='SKU00000000', name='', owned_codes=[]))
    state.add_sku(sku=Sku(associated_codes=[],
                          id='SKU00000000', name='', owned_codes=[]))


def test_add_batch():
    state = InventoryStateMachine()
    state.add_batch(batch=Batch(id='BAT00000000'))
    state.teardown()
