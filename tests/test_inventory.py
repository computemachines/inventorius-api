from conftest import clientContext
import pytest
import hypothesis.strategies as st
from hypothesis import assume
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, initialize, invariant, multiple, consumes, invariant
from inventory.data_models import Bin, Sku, Batch
import tests.data_models_strategies as dst

# bin1 = Bin(id="BIN1")
# bin2 = Bin(id="BIN2")
# sku1 = Sku(id="SKU1")


# def test_fail():
#     assert False


# def test_move(client):
#     client.post('/api/bins', json=bin1.to_json())
#     client.post('/api/bins', json=bin2.to_json())
#     client.post('/api/skus', json=sku1.to_json())
#     client.post('/api/receive', json={
#         "bin_id": bin1.id,
#         "sku_id": sku1.id,
#         "quantity": 2
#     })
#     client.post('/api/move', json={
#         "sku": sku1.id,
#         "from": bin1.id,
#         "to": bin2.id,
#         "count": 1})
#     rp = client.get('/api/bin/BIN1')
#     assert rp.status_code == 200
#     assert rp.is_json
#     assert rp.json['state']['contents'][0]['id'] == sku1.id
#     assert rp.json['state']['contents'][0]['quantity'] == 1


class InventoryStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super(InventoryStateMachine, self).__init__()
        with clientContext() as client:
            self.client = client
            self.model_skus = {}
            self.model_bins = {}
            self.model_batches = {}

    a_bin_id = Bundle("binId")
    a_sku_id = Bundle("skuId")
    a_batch_id = Bundle("batchId")

    @rule(target=a_sku_id, sku=dst.skus_())
    def new_sku(self, sku):
        resp = self.client.post('/api/skus', json=sku.to_json())
        if sku.id in self.model_skus.keys():
            assert resp.status_code == 409
            assert resp.is_json
            assert resp.json['type'] == 'duplicate-resource'
            return multiple()
        else:
            assert resp.status_code == 201
            self.model_skus[sku.id] = sku
            return sku.id

    @rule(target=a_bin_id, bin=dst.bins_())
    def new_bin(self, bin):
        resp = self.client.post('/api/bins', json=bin.to_json())
        if bin.id in self.model_bins.keys():
            assert resp.status_code == 409
            assert resp.is_json
            assert resp.json['type'] == 'duplicate-resource'
            return multiple()
        else:
            assert resp.status_code == 201
            self.model_bins[bin.id] = bin
            return bin.id

    @rule(target=a_batch_id, batch=dst.batches_())
    def add_batch(self, batch):
        resp = self.client.post('/api/batches', json=batch.to_json())
        if batch.id in self.model_batches.keys():
            assert resp.status_code == 409
            assert resp.json['type'] == 'duplicate-resource'
            assert resp.is_json
            return multiple()
        else:
            assert resp.status_code == 201
            self.model_batches[batch.id] = batch
            return batch.id

    @rule(binId=a_bin_id)
    def get_existing_bin(self, binId):
        rp = self.client.get(f'/api/bin/{binId}')
        assert rp.is_json

        assert binId in self.model_bins.keys()
        assert rp.status_code == 200
        assert self.model_bins[binId].props == rp.json['state']['props']
        found_bin = Bin.from_json(rp.json['state'])
        assert found_bin == self.model_bins[binId]

    @rule(binId=dst.label_("BIN"))
    def get_missing_bin(self, binId):
        assume(binId not in self.model_bins.keys())
        rp = self.client.get(f'/api/bin/{binId}')
        assert rp.status_code == 404
        assert rp.json['type'] == 'missing-resource'

    @rule(binId=a_bin_id, newProps=dst.json)
    def update_bin(self, binId, newProps):
        assume(self.model_bins[binId].props != newProps)
        rp = self.client.put(f'/api/bin/{binId}/props', json=newProps)
        self.model_bins[binId].props = newProps

    @rule(binId=a_bin_id, newProps=dst.json)
    def update_missing_bin(self, binId, newProps):
        assume(binId not in self.model_bins.keys())
        rp = self.client.put(f'/api/bin/{binId}/props', json=newProps)
        assert rp.status_code == 404
        assert rp.json['type'] == 'missing-resource'

    @ rule(binId=consumes(a_bin_id))
    def delete_bin(self, binId):
        rp = self.client.get(f'/api/bin{binId}')
        # TODO: Assert deleted


TestInventory = InventoryStateMachine.TestCase


def test_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents=[], id='BIN000000', props=None))
    state.get_existing_bin(binId=v1)
    state.teardown()


def test_update_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents=[], id='BIN000000', props=None))
    state.get_existing_bin(binId=v1)
    state.update_bin(binId=v1, newProps="New prop")
    state.get_existing_bin(binId=v1)

# def test_repeat_sku_push():
#     state = InventoryStateMachine()
#     v1 = state.add_sku(sku=Sku(associated_codes=[],
#                                id='SKU00000000', name='', owned_codes=[]))
#     state.add_sku(sku=Sku(associated_codes=[],
#                           id='SKU00000000', name='', owned_codes=[]))


# def test_add_batch():
#     state = InventoryStateMachine()
#     state.add_batch(batch=Batch(id='BAT00000000'))
#     state.teardown()
