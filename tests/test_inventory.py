import tests.data_models_strategies as dst
from inventory.data_models import Bin, Sku, Batch
from conftest import clientContext
import pytest
import hypothesis.strategies as st
from hypothesis import assume, settings, given
from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, initialize, invariant, multiple, consumes, invariant

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

    @rule(binId=a_bin_id)
    def get_existing_bin(self, binId):
        assert binId in self.model_bins.keys()

        rp = self.client.get(f'/api/bin/{binId}')
        assert rp.status_code == 200
        assert rp.is_json
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
        # assume(self.model_bins[binId].props != newProps)
        rp = self.client.patch(f'/api/bin/{binId}', json={"props": newProps})
        self.model_bins[binId].props = newProps
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

    @rule(binId=a_bin_id, newProps=dst.json)
    def update_missing_bin(self, binId, newProps):
        assume(binId not in self.model_bins.keys())
        rp = self.client.put(f'/api/bin/{binId}/props', json=newProps)
        assert rp.status_code == 404
        assert rp.json['type'] == 'missing-resource'

    @rule(binId=consumes(a_bin_id))
    def delete_empty_bin(self, binId):
        assume(self.model_bins[binId].contents == {})
        rp = self.client.delete(f'/api/bin/{binId}')
        del self.model_bins[binId]
        assert rp.status_code == 204
        assert rp.cache_control.no_cache

    @rule(binId=a_bin_id)
    def delete_nonempty_bin_noforce(self, binId):
        assume(self.model_bins[binId].contents != {})
        rp = self.client.delete(f'/api/bin/{binId}')
        assert rp.status_code == 403
        assert rp.is_json
        assert rp.json['type'] == 'dangerous-operation'

    @rule(binId=consumes(a_bin_id))
    def delete_nonempty_bin_force(self, binId):
        assume(self.model_bins[binId].contents != {})
        rp = self.client.delete(
            f'/api/bin/{binId}', query_string={"force": "true"})
        assert rp.status_code == 204
        assert rp.cache_control.no_cache

    @rule(binId=dst.label_("BIN"))
    def delete_missing_bin(self, binId):
        assume(binId not in self.model_bins.keys())
        rp = self.client.delete(f'/api/bin/{binId}')
        assert rp.status_code == 404
        assert rp.cache_control.no_cache
        assert rp.is_json
        assert rp.json['type'] == 'missing-resource'

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

    @rule(skuId=a_sku_id)
    def get_existing_sku(self, skuId):
        rp = self.client.get(f"/api/sku/{skuId}")
        assert rp.status_code == 200
        assert rp.is_json
        found_sku = Sku.from_json(rp.json['state'])
        assert found_sku == self.model_skus[skuId]

    @rule(skuId=dst.label_("SKU"))
    def get_missing_sku(self, skuId):
        assume(skuId not in self.model_skus.keys())
        rp = self.client.get(f"/api/sku/{skuId}")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == 'missing-resource'

    sku_patch = st.builds(lambda sku, use_keys: {
                          k: v for k, v in sku.__dict__.items() if k in use_keys},
                          dst.skus_(),
                          st.sets(st.sampled_from([
                              "owned_codes",
                              "associated_codes",
                              "name",
                              "props"
                          ])))

    @rule(skuId=a_sku_id, patch=sku_patch)
    def update_sku(self, skuId, patch):
        rp = self.client.patch(f'/api/sku/{skuId}', json=patch)
        for key in patch.keys():
            setattr(self.model_skus[skuId], key, patch[key])

    @rule(skuId=consumes(a_sku_id))
    def delete_unused_sku(self, skuId):
        # assume(self.model_skus[skuId].contents == [])
        rp = self.client.delete(f"/api/sku/{skuId}")
        assert rp.status_code == 204
        assert rp.cache_control.no_cache
        del self.model_skus[skuId]

    @invariant()
    def positive_quantities(self):
        for binId, bin in self.model_bins.items():
            for itemId, quantity in bin.contents.items():
                assert quantity >= 1

    @rule(skuId=consumes(a_sku_id))
    def delete_used_sku(self, skuId):
        assume(False)
        pass

    @rule(skuId=dst.label_("SKU"))
    def delete_missing_sku(self, skuId):
        assume(skuId not in self.model_skus.keys())
        rp = self.client.delete(f"/api/sku/{skuId}")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

    @rule(target=a_batch_id, batch=dst.batches_())
    def add_batch(self, batch):
        rp = self.client.post('/api/batches', json=batch.to_json())
        if batch.id in self.model_batches.keys():
            assert rp.status_code == 409
            assert rp.json['type'] == 'duplicate-resource'
            assert rp.is_json
            return multiple()
        else:
            assert rp.status_code == 201
            self.model_batches[batch.id] = batch
            return batch.id

    # Inventory operations

    @rule(binId=a_bin_id, skuId=a_sku_id, quantity=st.integers(1, 100))
    def receive(self, binId, skuId, quantity):
        rp = self.client.post(f"/api/bin/{binId}/contents", json={
            "id": skuId,
            "quantity": quantity
        })
        rp.status_code == 201
        self.model_bins[binId].contents[skuId] \
            = self.model_bins[binId].contents.get(skuId, 0) + quantity

    @rule(source_binId=a_bin_id, destination_binId=a_bin_id, data=st.data())
    def move(self, source_binId, destination_binId, data):
        assume(source_binId != destination_binId)
        # assume(skuId in self.model_bins[source_binId].contents.keys())
        assume(self.model_bins[source_binId].contents != {})
        skuId = data.draw(st.sampled_from(list(
            self.model_bins[source_binId].contents.keys())))
        # assume(quantity >= self.model_bins[source_binId].contents[skuId])
        quantity = data.draw(st.integers(
            1, self.model_bins[source_binId].contents[skuId]))
        rp = self.client.put(f'/api/bin/{source_binId}/contents/move', json={
            "id": skuId,
            "quantity": quantity,
            "destination": destination_binId
        })
        assert rp.status_code == 200


TestInventory = InventoryStateMachine.TestCase
TestInventory.settings = settings(
    max_examples=10000,
    stateful_step_count=20
)


def test_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.get_existing_bin(binId=v1)
    state.teardown()


def test_update_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.update_bin(binId=v1, newProps="New props")
    state.get_existing_bin(binId=v1)


def test_recreate_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.delete_empty_bin(binId=v1)
    state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.teardown()


def test_delete_sku():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    state.delete_unused_sku(skuId=v1)
    state.teardown()


@given(data=st.data())
def test_move_sku(data):
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000001', props=None))
    v3 = state.new_sku(sku=Sku(id='SKU000000'))
    state.receive(binId=v1, skuId=v3, quantity=1)
    state.move(data=data, destination_binId=v2, source_binId=v1)
    state.teardown()

# def test_update_sku():
#     state = InventoryStateMachine()
#     v1 = state.new_sku(sku=Sku(id="SKU000000"))


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
