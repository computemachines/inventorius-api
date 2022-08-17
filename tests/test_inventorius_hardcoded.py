from tests.test_inventorius import InventoriusStateMachine
import tests.data_models_strategies as dst
from inventorius.data_models import Bin, Sku, Batch, Props

import pytest
import hypothesis.strategies as st
from hypothesis import assume, settings, given


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


def test_delete_used_sku():
    state = InventoriusStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000'))
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[]))
    state.receive_sku(bin_id=v1, quantity=1, sku_id=v2)
    state.attempt_delete_used_sku(sku_id=v2)
    state.teardown()


def test_move_sku():
    state = InventoriusStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000'))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000001'))
    v3 = state.new_sku(sku=Sku(id='SKU000000'))
    state.receive_sku(bin_id=v1, sku_id=v3, quantity=1)

    data = dst.DataProxy('SKU000000', 1)
    state.move(data=data, destination_binId=v2, source_binId=v1)

    state.get_existing_bin(bin_id=v1)
    state.get_existing_bin(bin_id=v2)
    state.teardown()


def test_sku_locations():
    state = InventoriusStateMachine()
    state.delete_missing_sku(sku_id='SKU000000')
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000'))
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[]))
    state.receive_sku(bin_id=v1, quantity=1, sku_id=v2)
    state.sku_locations(sku_id=v2)
    state.teardown()


def test_delete_sku_after_force_delete_bin():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                               id='SKU000000', name='', owned_codes=[]))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000'))
    state.receive_sku(bin_id=v2, quantity=1, sku_id=v1)
    state.delete_nonempty_bin_force(bin_id=v2)
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


def test_delete_bin_with_batch():
    state = InventoriusStateMachine()
    # state.delete_missing_bin(bin_id='BIN000000')
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[], sku_id=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000'))
    state.receive_batch(batch_id=v1, bin_id=v2, quantity=1)
    state.delete_nonempty_bin_noforce(bin_id=v2)
    state.teardown()


def test_receive_batch():
    state = InventoriusStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', owned_codes=[], sku_id=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000'))
    state.receive_batch(batch_id=v1, bin_id=v2, quantity=1)
    state.get_existing_bin(v2)


# def test_search_name():
#     state = InventoriusStateMachine()
#     v1 = state.new_anonymous_batch(batch=Batch(associated_codes=[
#                                    'a'], id='BAT000000', name='', owned_codes=[], sku_id=None))
#     state.search(query='a')
#     state.teardown()

def test_get_missing_user():
    state = InventoriusStateMachine()
    state.get_missing_user(user_id='0')
    state.teardown()


def test_delete_missing_user():
    state = InventoriusStateMachine()
    state.delete_missing_user(user_id='0')
    state.teardown()


def test_new_user():
    state = InventoriusStateMachine()
    state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.teardown()


def test_get_existing_user():
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.get_existing_user(user_id=v1)
    state.teardown()


@given(data=st.data())
def test_create_existing_user(data):
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.create_existing_user(user_id=v1, data=data)
    state.teardown()


def test_whoami():
    state = InventoriusStateMachine()
    state.whoami()
    state.teardown()


def test_simple_login():
    state = InventoriusStateMachine()
    v1 = state.new_user(
        user={"id": 'tparker', "name": "tyler parker", "password": "12345678"})
    state.login_as(v1)
    state.whoami()
    state.teardown()


def test_update_existing_user():
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.update_existing_user(user_id=v1, user_patch={'password': '00000000'})
    state.teardown()


def test_change_password():
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.update_existing_user(user_id=v1, user_patch={'password': '00000010'})
    state.teardown()


def test_login_empty_password():
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.login_bad_password(password='', user_id=v1)
    state.teardown()


def test_delete_user():
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.login_as(user_id=v1)
    state.delete_existing_user(user_id=v1)
    state.teardown()


def test_login_delete_missing_bin():
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.login_as(user_id=v1)
    state.logout()
    state.delete_missing_bin(bin_id='BIN000000')
    state.teardown()


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
    state.delete_missing_user(user_id='00')
    state.delete_missing_user(user_id=';')
    v1 = state.new_user(user={'id': '1', 'name': '', 'password': '00000000'})
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


def test_was_undefined_key_error_01():
    state = InventoriusStateMachine()
    v1 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props={'_': None}))
    v2 = state.new_anonymous_batch(batch=Batch(associated_codes=[
    ], id='BAT575165', name='A', owned_codes=[], props={'': None}, sku_id=None))
    state.batch_locations(batch_id=v2)
    state.receive_batch(batch_id=v2, bin_id=v1, quantity=1)
    state.batch_locations(batch_id=v2)
    state.teardown()


def test_update_sku():
    state = InventoriusStateMachine()
    v1 = state.new_sku(sku=Sku(associated_codes=[],
                       id='SKU000000', name='', owned_codes=[], props={}))
    state.update_sku(patch={}, sku_id=v1)
    state.teardown()


def test_login_whoami():
    state = InventoriusStateMachine()
    v1 = state.new_user(user={'id': '0', 'name': '', 'password': '00000000'})
    state.login_as(user_id=v1)
    state.delete_existing_user(user_id=v1)
    state.whoami()
    state.teardown()


def test_change_password():
    state = InventoriusStateMachine()
    state.api_next()
    state.api_next()
    state.api_next()
    v1 = state.new_user(user={'id': '3', 'name': '', 'password': '11100111'})
    v2 = state.new_sku(sku=Sku(associated_codes=[],
                       id='SKU065793', name='A', owned_codes=[], props={}))
    state.login_as(user_id=v1)
    state.update_existing_user(user_id=v1, user_patch={
                               'password': '000000000'})
    state.whoami()
    state.teardown()


def test_release_anonymous_nothing():
    state = InventoriusStateMachine()
    v1 = state.new_anonymous_batch(batch=Batch(
        associated_codes=[], id='BAT000000', name='', owned_codes=[], props={}, sku_id=None))
    v2 = state.new_bin(bin=Bin(contents={}, id='BIN000000', props={}))
    state.release_batch(batch_id=v1, bin_id=v2, quantity=0)
    state.positive_quantities()
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
