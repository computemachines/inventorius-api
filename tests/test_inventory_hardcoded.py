from tests.test_inventory import InventoryStateMachine
import tests.data_models_strategies as dst
from inventory.data_models import Bin, Sku, Batch

import pytest
import hypothesis.strategies as st
from hypothesis import assume, settings, given


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
    state.receive_sku(bin_id=v1, quantity=1, sku_id=v2)
    state.attempt_delete_used_sku(sku_id=v2)
    state.teardown()


@given(data=st.data())
def test_move_sku(data):
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000001', props=None))
    v3 = state.new_sku(sku=Sku(id='SKU000000'))
    state.receive_sku(bin_id=v1, sku_id=v3, quantity=1)
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
    state.receive_sku(bin_id=v1, quantity=1, sku_id=v2)
    state.sku_locations(sku_id=v2)
    state.teardown()


def test_delete_sku_after_force_delete_bin():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    state.receive_sku(bin_id=v2, quantity=1, sku_id=v1)
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


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_change_batch_sku():
    state = InventoryStateMachine()
    sku0 = state.new_sku(sku=Sku(id='SKU000000', name=''))
    sku1 = state.new_sku(sku=Sku(id='SKU000001', name=''))

    data = dst.DataProxy(Batch(id='BAT000000', sku_id=sku0))
    batch0 = state.new_batch_existing_sku(data=data, sku_id=sku0)

    state.attempt_update_nonanonymous_batch_sku_id(
        batch_id=batch0, patch={}, sku_id=sku1)
    state.teardown()


def test_delete_bin_with_batch():
    state = InventoryStateMachine()
    # state.delete_missing_bin(bin_id='BIN000000')
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[], props=None, sku_id=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    state.receive_batch(batch_id=v1, bin_id=v2, quantity=1)
    state.delete_nonempty_bin_noforce(bin_id=v2)
    state.teardown()


def test_receive_batch():
    state = InventoryStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[], props=None, sku_id=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    state.receive_batch(batch_id=v1, bin_id=v2, quantity=1)
    state.get_existing_bin(v2)


def test_search_bin_id():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    state.search_existing_bin_id(bin_id=v1)
    state.teardown()


def test_search_bin_with_sku():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[], props=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    state.search_existing_bin_id(bin_id=v2)
    state.teardown()


def test_search_bin_with_batch():
    state = InventoryStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props=None))
    v2 = state.new_anonymous_batch(batch=Batch(associated_codes=[
    ], id='BAT000000', name='', owned_codes=[], props=None, sku_id=None))
    state.search_existing_bin_id(bin_id=v1)
    state.teardown()


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_search_existing_sku_owned_code():
    state = InventoryStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=["123"], props=None))
    state.search_existing_sku_owned_code(data=dst.DataProxy("123"), sku_id=v1)
    state.teardown()


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_search_existing_batch_owned_code():
    state = InventoryStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(associated_codes=[],
                                               id='BAT000000', name='', owned_codes=["123"], props=None, sku_id=None))
    state.search_existing_batch_owned_code(
        data=dst.DataProxy("123"), batch_id=v1)
    state.teardown()
