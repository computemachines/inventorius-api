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

    a_bin_id = Bundle("bin_id")
    a_sku_id = Bundle("sku_id")
    a_batch_id = Bundle("batch_id")

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

    @rule(bin_id=a_bin_id)
    def get_existing_bin(self, bin_id):
        assert bin_id in self.model_bins.keys()

        rp = self.client.get(f'/api/bin/{bin_id}')
        assert rp.status_code == 200
        assert rp.is_json
        assert self.model_bins[bin_id].props == rp.json['state']['props']
        found_bin = Bin.from_json(rp.json['state'])
        assert found_bin == self.model_bins[bin_id]

    @rule(bin_id=dst.label_("BIN"))
    def get_missing_bin(self, bin_id):
        assume(bin_id not in self.model_bins.keys())
        rp = self.client.get(f'/api/bin/{bin_id}')
        assert rp.status_code == 404
        assert rp.json['type'] == 'missing-resource'

    @rule(bin_id=a_bin_id, newProps=dst.json)
    def update_bin(self, bin_id, newProps):
        # assume(self.model_bins[bin_id].props != newProps)
        rp = self.client.patch(f'/api/bin/{bin_id}', json={"props": newProps})
        self.model_bins[bin_id].props = newProps
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

    @rule(bin_id=a_bin_id, newProps=dst.json)
    def update_missing_bin(self, bin_id, newProps):
        assume(bin_id not in self.model_bins.keys())
        rp = self.client.put(f'/api/bin/{bin_id}/props', json=newProps)
        assert rp.status_code == 404
        assert rp.json['type'] == 'missing-resource'

    @rule(bin_id=consumes(a_bin_id))
    def delete_empty_bin(self, bin_id):
        assume(self.model_bins[bin_id].contents == {})
        rp = self.client.delete(f'/api/bin/{bin_id}')
        del self.model_bins[bin_id]
        assert rp.status_code == 204
        assert rp.cache_control.no_cache

    @rule(bin_id=a_bin_id)
    def delete_nonempty_bin_noforce(self, bin_id):
        assume(self.model_bins[bin_id].contents != {})
        rp = self.client.delete(f'/api/bin/{bin_id}')
        assert rp.status_code == 403
        assert rp.is_json
        assert rp.json['type'] == 'dangerous-operation'

    @rule(bin_id=consumes(a_bin_id))
    def delete_nonempty_bin_force(self, bin_id):
        assume(self.model_bins[bin_id].contents != {})
        rp = self.client.delete(
            f'/api/bin/{bin_id}', query_string={"force": "true"})
        del self.model_bins[bin_id]
        assert rp.status_code == 204
        assert rp.cache_control.no_cache

    @rule(bin_id=dst.label_("BIN"))
    def delete_missing_bin(self, bin_id):
        assume(bin_id not in self.model_bins.keys())
        rp = self.client.delete(f'/api/bin/{bin_id}')
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

    @rule(sku_id=a_sku_id)
    def get_existing_sku(self, sku_id):
        rp = self.client.get(f"/api/sku/{sku_id}")
        assert rp.status_code == 200
        assert rp.is_json
        found_sku = Sku.from_json(rp.json['state'])
        assert found_sku == self.model_skus[sku_id]

    @rule(sku_id=dst.label_("SKU"))
    def get_missing_sku(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.get(f"/api/sku/{sku_id}")
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

    @rule(sku_id=a_sku_id, patch=sku_patch)
    def update_sku(self, sku_id, patch):
        rp = self.client.patch(f'/api/sku/{sku_id}', json=patch)
        for key in patch.keys():
            setattr(self.model_skus[sku_id], key, patch[key])

    @rule(sku_id=consumes(a_sku_id))
    def delete_unused_sku(self, sku_id):
        assume(not any([sku_id in bin.contents.keys()
                        for bin in self.model_bins.values()]))
        rp = self.client.delete(f"/api/sku/{sku_id}")
        assert rp.status_code == 204
        assert rp.cache_control.no_cache
        del self.model_skus[sku_id]

    @invariant()
    def positive_quantities(self):
        for bin_id, bin in self.model_bins.items():
            for itemId, quantity in bin.contents.items():
                assert quantity >= 1

    @rule(sku_id=a_sku_id)
    def sku_locations(self, sku_id):
        rp = self.client.get(f"/api/sku/{sku_id}/bins")
        assert rp.status_code == 200
        assert rp.is_json
        locations = rp.json['state']
        for bin_id, contents in locations.items():
            for itemId, quantity in contents.items():
                assert self.model_bins[bin_id].contents[itemId] == quantity
        model_locations = {}
        for bin_id, bin in self.model_bins.items():
            if sku_id in bin.contents.keys():
                model_locations[bin_id] = {
                    itemId: quantity for itemId, quantity in bin.contents.items() if itemId == sku_id}
        assert model_locations == locations

    @rule(sku_id=a_sku_id)
    def attempt_delete_used_sku(self, sku_id):
        assume(any([sku_id in bin.contents.keys()
                    for bin in self.model_bins.values()]))
        rp = self.client.delete(f"/api/sku/{sku_id}")
        assert rp.status_code == 403
        assert rp.is_json
        assert rp.json['type'] == "resource-in-use"

    @rule(sku_id=dst.label_("SKU"))
    def delete_missing_sku(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.delete(f"/api/sku/{sku_id}")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

    @rule(target=a_batch_id, data=st.data())
    def new_batch_existing_sku(self, data):
        assume(self.model_skus != {})
        sku_id = data.draw(st.sampled_from(list(self.model_skus.keys())))
        batch = data.draw(dst.batches_(sku_id=sku_id))
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

    @rule(bin_id=a_bin_id, sku_id=a_sku_id, quantity=st.integers(1, 100))
    def receive(self, bin_id, sku_id, quantity):
        rp = self.client.post(f"/api/bin/{bin_id}/contents", json={
            "id": sku_id,
            "quantity": quantity
        })
        rp.status_code == 201
        self.model_bins[bin_id].contents[sku_id] \
            = self.model_bins[bin_id].contents.get(sku_id, 0) + quantity

    @rule(source_binId=a_bin_id, destination_binId=a_bin_id, data=st.data())
    def move(self, source_binId, destination_binId, data):
        assume(source_binId != destination_binId)
        # assume(sku_id in self.model_bins[source_binId].contents.keys())
        assume(self.model_bins[source_binId].contents != {})
        sku_id = data.draw(st.sampled_from(list(
            self.model_bins[source_binId].contents.keys())))
        # assume(quantity >= self.model_bins[source_binId].contents[sku_id])
        quantity = data.draw(st.integers(
            1, self.model_bins[source_binId].contents[sku_id]))
        rp = self.client.put(f'/api/bin/{source_binId}/contents/move', json={
            "id": sku_id,
            "quantity": quantity,
            "destination": destination_binId
        })
        assert rp.status_code == 204
        assert rp.cache_control.no_cache


TestInventory = InventoryStateMachine.TestCase
TestInventory.settings = settings(
    max_examples=10000,
    stateful_step_count=10,
    deadline=None,
)


def test_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.get_existing_bin(bin_id=v1)
    state.teardown()


def test_update_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.update_bin(bin_id=v1, newProps="New props")
    state.get_existing_bin(bin_id=v1)


def test_recreate_bin():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.delete_empty_bin(bin_id=v1)
    state.new_bin(bin=Bin(id='BIN000000', props=None))
    state.teardown()


def test_delete_sku():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    state.delete_unused_sku(sku_id=v1)
    state.teardown()


def test_delete_used_sku():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    state.receive(bin_id=v1, quantity=1, sku_id=v2)
    state.attempt_delete_used_sku(sku_id=v2)
    state.teardown()


@given(data=st.data())
def test_move_sku(data):
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000001', props=None))
    v3 = state.new_sku(sku=Sku(id='SKU000000'))
    state.receive(bin_id=v1, sku_id=v3, quantity=1)
    state.move(data=data, destination_binId=v2, source_binId=v1)
    state.get_existing_bin(bin_id=v1)
    state.get_existing_bin(bin_id=v2)
    state.teardown()


def test_sku_locations():
    state = InventoryStateMachine()
    state.delete_missing_sku(sku_id='SKU000000')
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    state.receive(bin_id=v1, quantity=1, sku_id=v2)
    state.sku_locations(sku_id=v2)
    state.teardown()


def test_delete_sku_after_force_delete_bin():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    state.receive(bin_id=v2, quantity=1, sku_id=v1)
    state.delete_nonempty_bin_force(bin_id=v2)
    state.delete_unused_sku(sku_id=v1)
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
