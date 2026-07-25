from tests.test_inventorius import InventoriusStateMachine
import tests.data_models_strategies as dst
from inventorius.data_models import Bin, Sku, Batch, Props

import pytest


# This is all automatically generated test code from failed hypothesis test runs

def test_bin():
    state = InventoriusStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000'))
    state.get_existing_bin(bin_id=v1)
    state.teardown()


def test_update_bin():
    state = InventoriusStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000'))
    state.update_bin(bin_id=v1, newProps={"1": "New props"})
    state.get_existing_bin(bin_id=v1)


def test_recreate_bin():
    state = InventoriusStateMachine()
    v1 = state.new_bin(bin=Bin(id='BIN000000'))
    print(state)
    state.delete_empty_bin(bin_id=v1)
    state.new_bin(bin=Bin(id='BIN000000'))
    state.teardown()


def test_delete_sku():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[]))
    state.delete_unused_sku(sku_id=v1)
    state.teardown()


def test_update_nonexisting_batch():
    state = InventoriusStateMachine()
    state.update_nonexisting_batch(batch_id='BAT000000', patch={})
    state.teardown()


def test_recreate_batch():
    state = InventoriusStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000001', owned_codes=[], sku_id=None))
    state.delete_unused_batch(batch_id=v1)
    state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000001', owned_codes=[], sku_id=None))
    state.teardown()


def test_update_batch():
    state = InventoriusStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[], sku_id=None))
    state.update_batch(batch_id=v1, patch={'owned_codes': []})
    state.get_existing_batch(batch_id=v1)
    state.teardown()


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_update_sku_batch():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000001', name='', owned_codes=[]))
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000002', name='', owned_codes=[]))
    # state.delete_missing_sku(sku_id='SKU000000')
    data = dst.DataProxy(Batch(associated_codes=[], id='BAT000000',
                               owned_codes=[], props={"0": 0}, sku_id='SKU000001'))
    v2 = state.new_batch_existing_sku(data=data, sku_id=v1)
    state.attempt_update_nonanonymous_batch_sku_id(
        batch_id=v2, patch={}, sku_id='SKU000002')
    state.teardown()


def test_add_sku_to_anonymous_batch():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[]))
    v2 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[], sku_id=None))
    state.update_anonymous_batch_existing_sku_id(
        batch_id=v2, patch={}, sku_id=v1)
    state.teardown()


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_change_batch_sku():
    state = InventoriusStateMachine()
    sku0 = state.new_sku(sku=Sku(id='SKU000000', name=''))
    sku1 = state.new_sku(sku=Sku(id='SKU000001', name=''))

    data = dst.DataProxy(Batch(id='BAT000000', sku_id=sku0))
    batch0 = state.new_batch_existing_sku(data=data, sku_id=sku0)

    state.attempt_update_nonanonymous_batch_sku_id(
        batch_id=batch0, patch={}, sku_id=sku1)
    state.teardown()


# def test_search_name():
#     state = InventoriusStateMachine()
#     v1 = state.new_anonymous_batch(batch=Batch(associated_codes=[
#                                    'a'], id='BAT000000', name='', owned_codes=[], sku_id=None))
#     state.search(query='a')
#     state.teardown()

def test_get_missing_batch():
    state = InventoriusStateMachine()
    state.get_missing_batch(batch_id='BAT000000')
    state.teardown()


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_new_batch_bad_format_owned_codes():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                       id='SKU000000', name='', owned_codes=[], props={}))
    data = dst.DataProxy(Batch(associated_codes=[], id='BAT000000',
                         name='', owned_codes=[], props={}, sku_id='SKU000000'))
    state.new_batch_bad_format_owned_codes(bad_code='', data=data, sku_id=v1)
    state.teardown()


def test_update_batch_missing_sku():
    state = InventoriusStateMachine()
    state.delete_missing_sku(sku_id='SKU066304')
    state.delete_missing_sku(sku_id='SKU000256')
    v2 = state.new_anonymous_batch(batch=Batch(associated_codes=[
    ], id='BAT000000', name='', owned_codes=[], props={'a': [None]}, sku_id=None))
    state.attempt_update_anonymous_batch_missing_sku_id(
        batch_id=v2, patch={}, sku_id='SKU000000')
    state.teardown()


@pytest.mark.filterwarnings("ignore:.*example().*")
def test_update_batch_existing_sku():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                       id='SKU000000', name='', owned_codes=[], props={}))
    data = dst.DataProxy(Batch(associated_codes=[], id='BAT000000',
                         name='', owned_codes=[], props={}, sku_id='SKU000000'))
    v2 = state.new_batch_existing_sku(data=data, sku_id=v1)
    state.update_batch(batch_id=v2, patch={})
    state.teardown()

# def test_new_user_x0c():
#     state = InventoriusStateMachine()
#     state.new_user(user={'id': '\x0c', 'name': '', 'password': '00000000'})
#     state.teardown()


def test_update_sku():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                       id='SKU000000', name='', owned_codes=[], props={}))
    state.update_sku(patch={}, sku_id=v1)
    state.teardown()


def test_update_anonymous_batch_with_additional_field():
    state = InventoriusStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(associated_codes=[
    ], id='BAT000000', name='', owned_codes=[], props=Props(cost_per_case=None), sku_id=None))
    state.update_batch(batch_id=v1, patch={
                       'owned_codes': [], 'props': {'_': None}})
    state.teardown()


def test_clear_existing_props():
    state = InventoriusStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(associated_codes=[
    ], id='BAT000000', name='', owned_codes=[], props=Props(cost_per_case=None), sku_id=None))
    state.update_batch(batch_id=v1, patch={'props': {}})
    state.get_existing_batch(batch_id=v1)
    state.teardown()


def test_add_sku_to_anonymous_batch():
    state = InventoriusStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(associated_codes=[], id='BAT000000', name='', owned_codes=[], props=Props(
        cost_per_case=None, count_per_case=None, original_cost_per_case=None, original_count_per_case=None), sku_id=None))
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                       id='SKU000000', name='', owned_codes=[], props={}))
    state.update_anonymous_batch_existing_sku_id(batch_id=v1, patch={
                                                 'associated_codes': [], 'owned_codes': [], 'props': {}}, sku_id=v2)
    state.get_existing_batch(batch_id=v1)
    state.teardown()
