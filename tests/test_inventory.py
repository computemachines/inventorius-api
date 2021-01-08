from hypothesis.errors import NonInteractiveExampleWarning
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
        assert rp.status_code == 200
        assert rp.cache_control.no_cache
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
            for item_id, quantity in bin.contents.items():
                assert quantity >= 1

    @rule(sku_id=a_sku_id)
    def sku_locations(self, sku_id):
        rp = self.client.get(f"/api/sku/{sku_id}/bins")
        assert rp.status_code == 200
        assert rp.is_json
        locations = rp.json['state']
        for bin_id, contents in locations.items():
            for item_id, quantity in contents.items():
                assert self.model_bins[bin_id].contents[item_id] == quantity
        model_locations = {}
        for bin_id, bin in self.model_bins.items():
            if sku_id in bin.contents.keys():
                model_locations[bin_id] = {
                    item_id: quantity for item_id, quantity in bin.contents.items() if item_id == sku_id}
        assert model_locations == locations

    @rule(sku_id=dst.label_("SKU"))
    def missing_sku_locations(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.get(f"/api/sku/{sku_id}/bins")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

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

    @rule(target=a_batch_id, sku_id=a_sku_id, data=st.data())
    def new_batch_existing_sku(self, sku_id, data):
        assume(self.model_skus != {})
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

    @rule(batch=dst.batches_())
    def new_batch_new_sku(self, batch):
        assume(batch.sku_id)
        assume(batch.sku_id not in self.model_skus.keys())
        rp = self.client.post("/api/batches", json=batch.to_json())

        assert rp.status_code == 409
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

    @rule(target=a_batch_id, batch=dst.batches_(sku_id=None))
    def new_anonymous_batch(self, batch):
        assert not batch.sku_id
        rp = self.client.post("/api/batches", json=batch.to_json())

        if batch.id in self.model_batches.keys():
            assert rp.status_code == 409
            assert rp.json['type'] == 'duplicate-resource'
            assert rp.is_json
            return multiple()
        else:
            assert rp.status_code == 201
            self.model_batches[batch.id] = batch
            return batch.id

    @rule(batch_id=a_batch_id)
    def get_existing_batch(self, batch_id):
        rp = self.client.get(f"/api/batch/{batch_id}")
        assert rp.status_code == 200
        assert rp.is_json
        found_batch = Batch.from_json(rp.json['state'])
        assert found_batch == self.model_batches[batch_id]

    @rule(batch_id=dst.label_("BAT"))
    def get_missing_batch(self, batch_id):
        assume(batch_id not in self.model_batches.keys())
        rp = self.client.get(f"/api/batch/{batch_id}")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

    batch_patch = st.builds(lambda batch, use_keys: {
        k: v for k, v in batch.__dict__.items() if k in use_keys},
        dst.skus_(),
        st.sets(st.sampled_from([
            "owned_codes",
            "associated_codes",
            "props"
        ])))

    @rule(batch_id=a_batch_id, patch=batch_patch)
    def update_batch(self, batch_id, patch):
        rp = self.client.patch(f'/api/batch/{batch_id}', json=patch)
        assert rp.status_code == 204
        assert rp.cache_control.no_cache
        for key in patch.keys():
            setattr(self.model_batches[batch_id], key, patch[key])

    @rule(batch_id=dst.label_("BAT"), patch=batch_patch)
    def update_nonexisting_batch(self, batch_id, patch):
        assume(batch_id not in self.model_batches.keys())
        rp = self.client.patch(f'/api/batch/{batch_id}', json=patch)
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

    @rule(batch_id=a_batch_id, sku_id=a_sku_id, patch=batch_patch)
    def attempt_update_nonanonymous_batch_sku_id(self, batch_id, sku_id, patch):
        assume(self.model_batches[batch_id].sku_id)
        assume(sku_id != self.model_batches[batch_id].sku_id)
        patch['sku_id'] = sku_id
        rp = self.client.patch(f'/api/batch/{batch_id}', json=patch)
        assert rp.status_code == 409
        assert rp.is_json
        assert rp.json['type'] == "dangerous-operation"

    @rule(batch_id=a_batch_id, sku_id=a_sku_id, patch=batch_patch)
    def update_anonymous_batch_existing_sku_id(self, batch_id, sku_id, patch):
        assume(self.model_batches[batch_id].sku_id)
        patch['sku_id'] = sku_id
        rp = self.client.patch(f"/api/batch/{batch_id}", json=patch)
        assert rp.status_code == 204
        assert rp.cache_control.no_cache
        for key in patch.keys():
            setattr(self.model_batches[batch_id], key, patch[key])

    @rule(batch_id=a_batch_id, sku_id=dst.label_("SKU"), patch=batch_patch)
    def attempt_update_anonymous_batch_missing_sku_id(self, batch_id, sku_id, patch):
        assume(sku_id not in self.model_skus.keys())
        patch['sku_id'] = sku_id
        rp = self.client.patch(f"/api/batch/{batch_id}", json=patch)
        assert rp.status_code == 409
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

    @rule(batch_id=consumes(a_batch_id))
    def delete_unused_batch(self, batch_id):
        assume(not any([batch_id in bin.contents.keys()
                        for bin in self.model_bins.values()]))
        rp = self.client.delete(f"/api/batch/{batch_id}")
        del self.model_batches[batch_id]
        assert rp.status_code == 204
        assert rp.cache_control.no_cache

    @rule(batch_id=a_batch_id)
    def batch_locations(self, batch_id):
        rp = self.client.get(f"/api/batch/{batch_id}/bins")
        assert rp.status_code == 200
        assert rp.is_json
        locations = rp.json['state']

        for bin_id, contents in locations.items():
            for item_id, quantity in contents.items():
                assert self.model_bins[bin_id].contents[item_id] == quantity

        model_locations = {}
        for bin_id, bin in self.model_bins.items():
            if batch_id in bin.contents.keys():
                model_locations[bin_id] = {
                    item_id: quantity for item_id, quantity in bin.contents.items() if item_id == batch_id
                }
        assert model_locations == locations

    @rule(batch_id=dst.label_("BAT"))
    def nonexisting_batch_locations(self, batch_id):
        assume(batch_id not in self.model_batches.keys())
        rp = self.client.get(f"/api/batch/{batch_id}/bins")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == "missing-resource"

    @rule(sku_id=a_sku_id)
    def sku_batchs(self, sku_id):
        rp = self.client.get(f"/api/sku/{sku_id}/batches")
        assert rp.status_code == 200
        assert rp.is_json
        batch_ids = rp.json['state']

        model_batch_ids = [
            batch.id for batch in self.model_batches.values() if batch.sku_id == sku_id]
        assert batch_ids == model_batch_ids

    @rule(sku_id=dst.label_("SKU"))
    def missing_sku_batches(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.get(f"/api/sku/{sku_id}/batches")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json['type'] == 'missing-resource'

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

        self.model_bins[source_binId].contents[sku_id] -= quantity
        self.model_bins[destination_binId].contents[sku_id] = quantity \
            + self.model_bins[destination_binId].contents.get(sku_id, 0)
        if self.model_bins[source_binId].contents[sku_id] == 0:
            del self.model_bins[source_binId].contents[sku_id]


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


def test_move_sku_given():
    test_move_sku()


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


def test_update_nonexisting_batch():
    state = InventoryStateMachine()
    state.update_nonexisting_batch(batch_id='BAT000000', patch={})
    state.teardown()


def test_recreate_batch():
    state = InventoryStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000001', owned_codes=[], props=None, sku_id=None))
    state.delete_unused_batch(batch_id=v1)
    state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000001', owned_codes=[], props=None, sku_id=None))
    state.teardown()


def test_update_batch():
    state = InventoryStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[''], props=None, sku_id=None))
    state.update_batch(batch_id=v1, patch={'owned_codes': []})
    state.get_existing_batch(batch_id=v1)
    state.teardown()


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_update_sku_batch():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000001', name='', owned_codes=[], props=None))
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000002', name='', owned_codes=[], props=None))
    # state.delete_missing_sku(sku_id='SKU000000')
    data = dst.DataProxy(Batch(associated_codes=[], id='BAT000000',
                               owned_codes=[], props=0, sku_id='SKU000001'))
    v2 = state.new_batch_existing_sku(data=data, sku_id=v1)
    state.attempt_update_nonanonymous_batch_sku_id(
        batch_id=v2, patch={}, sku_id='SKU000002')
    state.teardown()


def test_add_sku_to_anonymous_batch():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    v2 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[], props=None, sku_id=None))
    state.update_anonymous_batch_existing_sku_id(
        batch_id=v2, patch={}, sku_id=v1)
    state.teardown()


def test_change_batch_sku():
    state = InventoryStateMachine()
    sku0 = state.new_sku(sku=Sku(id='SKU000000', name=''))
    sku1 = state.new_sku(sku=Sku(id='SKU000001', name=''))

    data = dst.DataProxy(Batch(id='BAT000000', sku_id=sku0))
    batch0 = state.new_batch_existing_sku(data=data, sku_id=sku0)

    state.update_anonymous_batch_existing_sku_id(
        batch_id=batch0, patch={}, sku_id=sku1)
    state.teardown()
