from conftest import clientContext
import pytest
import hypothesis.strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, initialize, invariant, multiple
from inventory.data_models import Bin, Sku, Uniq, Batch
import tests.data_models_strategies as dst

bin1 = Bin(id="BIN1")
bin2 = Bin(id="BIN2")
sku1 = Sku(id="SKU1")
uniq1 = Uniq(id="UNIQ1", bin_id=bin1.id)


@pytest.mark.skip
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
    assert rp.json['contents'][0]['id'] == sku1.id
    assert rp.json['contents'][0]['quantity'] == 1


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
        else:
            assert resp.status_code == 201
        return sku.id

    @rule(target=binIds, bin=dst.bins_())
    def add_bin(self, bin):
        resp = self.client.post('/api/bins', json=bin.to_json())
        if bin.id in self.bins.keys():
            assert resp.status_code == 409
            assert resp.is_json
            assert resp.json['type'] == 'duplicate-bin'
        else:
            assert resp.status_code == 201
            self.bins[bin.id] = bin
        return bin.id

    @rule(binId=binIds)
    def get_bin(self, binId):
        rp = self.client.get(f'/api/bin/{binId}')
        assert rp.is_json
        assert self.bins[binId].props == rp.json['state']['props']


TestInventory = InventoryStateMachine.TestCase
