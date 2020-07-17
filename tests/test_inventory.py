from conftest import clientContext
import hypothesis.strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, initialize, invariant, multiple
from inventory.data_models import Bin, Sku, Uniq, Batch
import tests.data_models_strategies as dst

bin1 = Bin(id="BIN1")
bin2 = Bin(id="BIN2")
sku1 = Sku(id="SKU1")
uniq1 = Uniq(id="UNIQ1", bin_id=bin1.id)


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

    bins = Bundle("bins")

    @rule(target=bins, bin=dst.bins_())
    def add_bin(self, bin):
        self.client.post('/api/bins', json=bin.to_json())
        return bin

    @rule(bin=bins)
    def get_bin(self, bin):
        rp = self.client.get(f'/api/bin/{bin.id}')
        assert rp.is_json
        assert bin.props == rp.json['state']['props']


TestInventory = InventoryStateMachine.TestCase
