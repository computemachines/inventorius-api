import itertools as it
import os
from datetime import timedelta

import hypothesis.strategies as st
import pytest
from conftest import clientContext
from hypothesis import assume, given, reproduce_failure, settings
from hypothesis.errors import NonInteractiveExampleWarning
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    consumes,
    initialize,
    invariant,
    multiple,
    rule,
)
from inventorius.data_models import Batch, Bin, Props, Sku, Subdoc

import tests.data_models_strategies as dst

# @reproduce_failure('5.44.0', b'AXicY2BkUGcAA0ZGKC0KZgIABDQAQw==')


class InventoriusStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super(InventoriusStateMachine, self).__init__()
        with clientContext() as client:
            self.client = client
            self.model_skus = {}
            self.model_bins = {}
            self.model_batches = {}
            self.model_users = {}
            self.logged_in_as = None

    a_bin_id = Bundle("bin_id")
    a_sku_id = Bundle("sku_id")
    a_batch_id = Bundle("batch_id")
    a_user_id = Bundle("user_id")

    @rule(target=a_user_id, user=dst.users_())
    def new_user(self, user):
        resp = self.client.post("/api/users", json=user)
        if user["id"] in self.model_users.keys():
            assert resp.status_code == 409
            assert resp.is_json
            assert resp.json["type"] == "duplicate-resource"
            return multiple()
        else:
            assert resp.status_code == 201
            self.model_users[user["id"]] = user
            return user["id"]

    @rule(user_id=consumes(a_user_id))
    def delete_existing_user(self, user_id):
        resp = self.client.delete(f"/api/user/{user_id}")
        del self.model_users[user_id]
        assert resp.status_code == 200

        if self.logged_in_as == user_id:
            self.logged_in_as = None

    @rule(user_id=a_user_id)
    def get_existing_user(self, user_id):
        resp = self.client.get(f"/api/user/{user_id}")
        assert resp.status_code == 200
        assert resp.is_json
        found_user = resp.json["state"]
        model_user = self.model_users[user_id]
        assert model_user["id"] == found_user["id"]
        assert model_user["name"] == found_user["name"]

    @rule(user_id=dst.ids)
    def get_missing_user(self, user_id):
        assume(user_id not in self.model_users.keys())
        resp = self.client.get(f"/api/user/{user_id}")
        assert resp.status_code == 404
        assert resp.is_json
        assert resp.json["type"] == "missing-resource"

    @rule(user_id=dst.ids)
    def delete_missing_user(self, user_id):
        assume(user_id not in self.model_users.keys())
        resp = self.client.delete(f"/api/user/{user_id}")
        assert resp.status_code == 404
        assert resp.is_json
        assert resp.json["type"] == "missing-resource"

    @rule(user_id=a_user_id, data=st.data())
    def create_existing_user(self, user_id, data):
        user = data.draw(dst.users_(id=user_id))
        resp = self.client.post("/api/users", json=user)
        assert resp.status_code == 409
        assert resp.is_json
        assert resp.json["type"] == "duplicate-resource"

    user_patch = st.builds(
        lambda user, use_keys: {k: v for k, v in user.items() if k in use_keys},
        dst.users_(),
        st.sets(
            st.sampled_from(
                [
                    "name",
                    "password",
                ]
            )
        ),
    )

    @rule(user_id=a_user_id, user_patch=user_patch)
    def update_existing_user(self, user_id, user_patch):
        rp = self.client.patch(f"/api/user/{user_id}", json=user_patch)
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

        if "password" in user_patch:
            # changing password should cause log out
            self.logged_in_as = None

        for key in user_patch.keys():
            self.model_users[user_id][key] = user_patch[key]

    @rule(user_id=a_user_id)
    def login_as(self, user_id):
        rp = self.client.post("/api/login", json={"id": user_id, "password": self.model_users[user_id]["password"]})
        assert rp.cache_control.no_cache
        self.logged_in_as = user_id

    @rule(user_id=a_user_id, password=st.text())
    def login_bad_password(self, user_id, password):
        assume(password != self.model_users[user_id])
        rp = self.client.post("/api/login", json={"id": user_id, "password": password})
        assert rp.status_code == 401
        assert rp.cache_control.no_cache
        assert rp.is_json

    @rule(user=dst.users_())
    def login_bad_username(self, user):
        assume(user["id"] not in self.model_users)
        rp = self.client.post("/api/login", json={"id": user["id"], "password": user["password"]})
        assert rp.status_code == 401
        assert rp.cache_control.no_cache
        assert rp.is_json

    @rule()
    def logout(self):
        rp = self.client.post("/api/logout")
        assert rp.status_code == 200
        assert rp.cache_control.no_cache
        assert rp.is_json
        self.logged_in_as = None

    @rule()
    def whoami(self):
        rp = self.client.get("/api/whoami")
        assert rp.status_code == 200
        assert rp.is_json
        if self.logged_in_as:
            assert rp.json["id"] == self.logged_in_as
        else:
            assert rp.json["id"] == None

    @rule(target=a_bin_id, bin=dst.bins_())
    def new_bin(self, bin):
        resp = self.client.post("/api/bins", json=bin.to_dict(mask_default=True))
        if bin.id in self.model_bins.keys():
            assert resp.status_code == 409
            assert resp.is_json
            assert resp.json["type"] == "duplicate-resource"
            return multiple()
        else:
            assert resp.status_code == 201
            self.model_bins[bin.id] = bin
            return bin.id

    @rule(bin_id=a_bin_id)
    def get_existing_bin(self, bin_id):
        assert bin_id in self.model_bins.keys()

        rp = self.client.get(f"/api/bin/{bin_id}")
        assert rp.status_code == 200
        assert rp.is_json
        assert self.model_bins[bin_id].props == rp.json["state"].get("props")
        found_bin = Bin.from_json(rp.json["state"])
        assert found_bin == self.model_bins[bin_id]

    @rule(bin_id=dst.label_("BIN"))
    def get_missing_bin(self, bin_id):
        assume(bin_id not in self.model_bins.keys())
        rp = self.client.get(f"/api/bin/{bin_id}")
        assert rp.status_code == 404
        assert rp.json["type"] == "missing-resource"

    @rule(bin_id=a_bin_id, newProps=dst.propertyDicts)
    def update_bin(self, bin_id, newProps):
        # assume(self.model_bins[bin_id].props != newProps)
        rp = self.client.patch(f"/api/bin/{bin_id}", json={"id": bin_id, "props": newProps})
        self.model_bins[bin_id].props = newProps
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

    @rule(bin_id=a_bin_id, newProps=dst.json)
    def update_missing_bin(self, bin_id, newProps):
        assume(bin_id not in self.model_bins.keys())
        rp = self.client.put(f"/api/bin/{bin_id}/props", json=newProps)
        assert rp.status_code == 404
        assert rp.json["type"] == "missing-resource"

    @rule(bin_id=consumes(a_bin_id))
    def delete_empty_bin(self, bin_id):
        assume(self.model_bins[bin_id].contents == {})
        rp = self.client.delete(f"/api/bin/{bin_id}")
        del self.model_bins[bin_id]
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

    @rule(bin_id=a_bin_id)
    def delete_nonempty_bin_noforce(self, bin_id):
        assume(self.model_bins[bin_id].contents != {})
        rp = self.client.delete(f"/api/bin/{bin_id}")
        assert rp.status_code == 405
        assert rp.is_json
        assert rp.json["type"] == "dangerous-operation"

    @rule(bin_id=consumes(a_bin_id))
    def delete_nonempty_bin_force(self, bin_id):
        assume(self.model_bins[bin_id].contents != {})
        rp = self.client.delete(f"/api/bin/{bin_id}", query_string={"force": "true"})
        del self.model_bins[bin_id]
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

    @rule(bin_id=dst.label_("BIN"))
    def delete_missing_bin(self, bin_id):
        assume(bin_id not in self.model_bins.keys())
        rp = self.client.delete(f"/api/bin/{bin_id}")
        assert rp.status_code == 404
        assert rp.cache_control.no_cache
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    @rule(target=a_sku_id, sku=dst.skus_())
    def new_sku(self, sku):
        resp = self.client.post("/api/skus", json=sku.to_dict(mask_default=True))
        if sku.id in self.model_skus.keys():
            assert resp.status_code == 409
            assert resp.is_json
            assert resp.json["type"] == "duplicate-resource"
            return multiple()
        else:
            assert resp.status_code == 201
            self.model_skus[sku.id] = sku
            return sku.id

    @rule(sku=dst.skus_(), bad_code=st.sampled_from(["", " ", "\t", "     ", " 123", "1 2 3", "123 abc"]))
    def new_sku_bad_format_owned_codes(self, sku, bad_code):
        assume(sku.id not in self.model_skus.keys())
        temp_sku = Sku.from_json(sku.to_json())
        temp_sku.owned_codes.append(bad_code)
        resp = self.client.post("/api/skus", json=temp_sku.to_dict())
        assert resp.status_code == 400
        assert resp.is_json
        assert resp.json["type"] == "validation-error"

        temp_sku = Sku.from_json(sku.to_json())
        temp_sku.associated_codes.append(bad_code)
        resp = self.client.post("/api/skus", json=temp_sku.to_dict())
        assert resp.status_code == 400
        assert resp.is_json
        assert resp.json["type"] == "validation-error"

    @rule(sku_id=a_sku_id)
    def get_existing_sku(self, sku_id):
        rp = self.client.get(f"/api/sku/{sku_id}")
        assert rp.status_code == 200
        assert rp.is_json
        found_sku = Sku(**rp.json["state"])
        assert found_sku == self.model_skus[sku_id]

    @rule(sku_id=dst.label_("SKU"))
    def get_missing_sku(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.get(f"/api/sku/{sku_id}")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    sku_patch = st.builds(
        lambda sku, use_keys: {k: v for k, v in sku.__dict__.items() if k in use_keys},
        dst.skus_(),
        st.sets(st.sampled_from(["owned_codes", "associated_codes", "name", "props"])),
    )

    @rule(sku_id=a_sku_id, patch=sku_patch)
    def update_sku(self, sku_id, patch):
        rp = self.client.patch(f"/api/sku/{sku_id}", json=patch)
        assert rp.status_code == 200
        assert rp.cache_control.no_cache
        for key in patch.keys():
            setattr(self.model_skus[sku_id], key, patch[key])

    @rule(sku_id=consumes(a_sku_id))
    def delete_unused_sku(self, sku_id):
        assume(not any([sku_id in bin.contents.keys() for bin in self.model_bins.values()]))
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
        locations = rp.json["state"]
        for bin_id, contents in locations.items():
            for item_id, quantity in contents.items():
                assert self.model_bins[bin_id].contents[item_id] == quantity
        model_locations = {}
        for bin_id, bin in self.model_bins.items():
            if sku_id in bin.contents.keys():
                model_locations[bin_id] = {
                    item_id: quantity for item_id, quantity in bin.contents.items() if item_id == sku_id
                }
        assert model_locations == locations

    @rule(sku_id=dst.label_("SKU"))
    def missing_sku_locations(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.get(f"/api/sku/{sku_id}/bins")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    @rule(sku_id=a_sku_id)
    def attempt_delete_used_sku(self, sku_id):
        assume(any([sku_id in bin.contents.keys() for bin in self.model_bins.values()]))
        rp = self.client.delete(f"/api/sku/{sku_id}")
        assert rp.status_code == 403
        assert rp.is_json
        assert rp.json["type"] == "resource-in-use"

    @rule(sku_id=dst.label_("SKU"))
    def delete_missing_sku(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.delete(f"/api/sku/{sku_id}")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    @rule(target=a_batch_id, sku_id=a_sku_id, data=st.data())
    def new_batch_existing_sku(self, sku_id, data):
        # assume(self.model_skus != {})  # TODO: check if this is necessary
        batch = data.draw(dst.batches_(sku_id=sku_id))

        rp = self.client.post("/api/batches", json=batch.to_dict(mask_default=True))

        if batch.id in self.model_batches.keys():
            assert rp.status_code == 409
            assert rp.json["type"] == "duplicate-resource"
            assert rp.is_json
            return multiple()
        else:
            assert rp.status_code == 201
            self.model_batches[batch.id] = batch
            return batch.id

    @rule(
        data=dst.data(),
        sku_id=a_sku_id,
        bad_code=st.sampled_from(["", " ", "\t", "     ", " 123", "1 2 3", "123 abc"]),
    )
    def new_batch_bad_format_owned_codes(self, data, sku_id, bad_code):
        batch = data.draw(dst.batches_(sku_id=sku_id))
        assume(batch.id not in self.model_batches.keys())

        temp_batch = Batch.from_json(batch.to_json())
        temp_batch.owned_codes.append(bad_code)
        resp = self.client.post("/api/batches", json=temp_batch.to_dict())
        assert resp.status_code == 400
        assert resp.is_json
        assert resp.json["type"] == "validation-error"

        temp_batch = Batch.from_json(batch.to_json())
        temp_batch.associated_codes.append(bad_code)
        resp = self.client.post("/api/batches", json=temp_batch.to_dict())
        assert resp.status_code == 400
        assert resp.is_json
        assert resp.json["type"] == "validation-error"

    @rule(batch=dst.batches_())
    def new_batch_new_sku(self, batch):
        assume(batch.sku_id)
        assume(batch.sku_id not in self.model_skus.keys())
        rp = self.client.post("/api/batches", json=batch.to_json())

        assert rp.status_code == 409
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    @rule(target=a_batch_id, batch=dst.batches_(sku_id=None))
    def new_anonymous_batch(self, batch):
        assert not batch.sku_id
        rp = self.client.post("/api/batches", json=batch.to_dict(mask_default=True))

        if batch.id in self.model_batches.keys():
            assert rp.status_code == 409
            assert rp.json["type"] == "duplicate-resource"
            assert rp.is_json
            return multiple()
        else:
            assert rp.json.get("type") is None
            assert rp.status_code == 201
            self.model_batches[batch.id] = batch
            return batch.id

    @rule(batch_id=a_batch_id)
    def get_existing_batch(self, batch_id):
        rp = self.client.get(f"/api/batch/{batch_id}")
        assert rp.status_code == 200
        assert rp.is_json
        found_batch = Batch.from_json(rp.json["state"])
        assert found_batch == self.model_batches[batch_id]

    @rule(batch_id=dst.label_("BAT"))
    def get_missing_batch(self, batch_id):
        assume(batch_id not in self.model_batches.keys())
        rp = self.client.get(f"/api/batch/{batch_id}")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    batch_patch = st.builds(
        lambda batch, use_keys: {k: v for k, v in batch.__dict__.items() if k in use_keys},
        dst.skus_(),
        st.sets(st.sampled_from(["owned_codes", "associated_codes", "props"])),
    )

    @rule(batch_id=a_batch_id, patch=batch_patch)
    def update_batch(self, batch_id, patch):
        patch["id"] = batch_id
        rp = self.client.patch(f"/api/batch/{batch_id}", json=patch)
        assert rp.status_code == 200
        assert rp.cache_control.no_cache
        for key in patch.keys():
            if key == "props":
                setattr(self.model_batches[batch_id], "props", Props(**patch["props"]))
            else:
                setattr(self.model_batches[batch_id], key, patch[key])

    @rule(batch_id=dst.label_("BAT"), patch=batch_patch)
    def update_nonexisting_batch(self, batch_id, patch):
        patch["id"] = batch_id

        assume(batch_id not in self.model_batches.keys())
        rp = self.client.patch(f"/api/batch/{batch_id}", json=patch)
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    @rule(batch_id=a_batch_id, sku_id=a_sku_id, patch=batch_patch)
    def attempt_update_nonanonymous_batch_sku_id(self, batch_id, sku_id, patch):
        patch["id"] = batch_id

        assume(self.model_batches[batch_id].sku_id)
        assume(sku_id != self.model_batches[batch_id].sku_id)
        patch["sku_id"] = sku_id
        rp = self.client.patch(f"/api/batch/{batch_id}", json=patch)
        assert rp.status_code == 405
        assert rp.is_json
        assert rp.json["type"] == "dangerous-operation"

    @rule(batch_id=a_batch_id, sku_id=a_sku_id, patch=batch_patch)
    def update_anonymous_batch_existing_sku_id(self, batch_id, sku_id, patch):
        patch["id"] = batch_id

        assume(not self.model_batches[batch_id].sku_id)
        patch["sku_id"] = sku_id
        rp = self.client.patch(f"/api/batch/{batch_id}", json=patch)
        assert rp.status_code == 200
        assert rp.cache_control.no_cache
        for key in patch.keys():
            if key == "props":
                setattr(self.model_batches[batch_id], key, Props(**patch[key]))
            else:
                setattr(self.model_batches[batch_id], key, patch[key])

    @rule(batch_id=a_batch_id, sku_id=dst.label_("SKU"), patch=batch_patch)
    def attempt_update_anonymous_batch_missing_sku_id(self, batch_id, sku_id, patch):
        patch["id"] = batch_id

        assume(sku_id not in self.model_skus.keys())
        patch["sku_id"] = sku_id
        rp = self.client.patch(f"/api/batch/{batch_id}", json=patch)
        assert rp.status_code == 400
        assert rp.is_json
        assert rp.json["type"] == "validation-error"
        assert {"name": "sku_id", "reason": "must be an existing sku id"} in rp.json["invalid-params"]

    @rule(batch_id=consumes(a_batch_id))
    def delete_unused_batch(self, batch_id):
        assume(not any([batch_id in bin.contents.keys() for bin in self.model_bins.values()]))
        rp = self.client.delete(f"/api/batch/{batch_id}")
        del self.model_batches[batch_id]
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

    @rule(batch_id=a_batch_id)
    def batch_locations(self, batch_id):
        rp = self.client.get(f"/api/batch/{batch_id}/bins")
        assert rp.status_code == 200
        assert rp.is_json
        locations = rp.json["state"]

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
        assert rp.json["type"] == "missing-resource"

    @rule(sku_id=a_sku_id)
    def sku_batchs(self, sku_id):
        rp = self.client.get(f"/api/sku/{sku_id}/batches")
        assert rp.status_code == 200
        assert rp.is_json
        batch_ids = rp.json["state"]

        model_batch_ids = [batch.id for batch in self.model_batches.values() if batch.sku_id == sku_id]
        assert batch_ids == model_batch_ids

    @rule(sku_id=dst.label_("SKU"))
    def missing_sku_batches(self, sku_id):
        assume(sku_id not in self.model_skus.keys())
        rp = self.client.get(f"/api/sku/{sku_id}/batches")
        assert rp.status_code == 404
        assert rp.is_json
        assert rp.json["type"] == "missing-resource"

    # Inventorius operations

    @rule(bin_id=a_bin_id, sku_id=a_sku_id, quantity=st.integers(1, 100))
    def receive_sku(self, bin_id, sku_id, quantity):
        rp = self.client.post(f"/api/bin/{bin_id}/contents", json={"id": sku_id, "quantity": quantity})
        rp.status_code == 201
        self.model_bins[bin_id].contents[sku_id] = self.model_bins[bin_id].contents.get(sku_id, 0) + quantity

    @rule(bin_id=dst.label_("BIN"), sku_id=dst.label_("SKU"), quantity=st.integers(1, 100))
    def receive_missing_sku_bin(self, bin_id, sku_id, quantity):
        rp = self.client.post(f"/api/bin/{bin_id}/contents", json={"id": sku_id, "quantity": quantity})
        if bin_id not in self.model_bins.keys():
            assert rp.status_code == 404
            assert rp.is_json
            assert rp.json["type"] == "missing-resource"
        elif sku_id not in self.model_skus.keys():
            assert rp.status_code == 409
            assert rp.is_json
            assert rp.json["type"] == "missing-resource"

    @rule(bin_id=a_bin_id, batch_id=a_batch_id, quantity=st.integers(1, 100))
    def receive_batch(self, bin_id, batch_id, quantity):
        rp = self.client.post(f"/api/bin/{bin_id}/contents", json={"id": batch_id, "quantity": quantity})
        rp.status_code == 201
        self.model_bins[bin_id].contents[batch_id] = self.model_bins[bin_id].contents.get(batch_id, 0) + quantity

    @rule(bin_id=a_bin_id, batch_id=a_batch_id, quantity=st.integers(1, 100))
    def receive_missing_batch_bin(self, bin_id, batch_id, quantity):
        assume(bin_id not in self.model_bins.keys() or batch_id not in self.model_batches.keys())
        rp = self.client.post(f"/api/bin/{bin_id}/contents", json={"id": batch_id, "quantity": quantity})
        if bin_id not in self.model_bins.keys():
            assert rp.status_code == 404
            assert rp.is_json
            assert rp.json["type"] == "missing-resource"
        elif batch_id not in self.model_batches.keys():
            assert rp.status_code == 409
            assert rp.is_json
            assert rp.json["type"] == "missing-resource"

    @rule(bin_id=a_bin_id, sku_id=a_sku_id, quantity=st.integers(-100, 0))
    def release_sku(self, bin_id, sku_id, quantity):
        rp = self.client.post(
            f"/api/bin/{bin_id}/contents",
            json={
                "id": sku_id,
                "quantity": quantity,
            },
        )
        if quantity + self.model_bins[bin_id].contents.get(sku_id, 0) < 0:
            assert rp.status_code == 405
            assert rp.is_json
            assert rp.json["type"] == "insufficient-quantity"
        else:
            assert rp.status_code == 201
            self.model_bins[bin_id].contents[sku_id] = self.model_bins[bin_id].contents.get(sku_id, 0) + quantity
            if self.model_bins[bin_id].contents[sku_id] == 0:
                del self.model_bins[bin_id].contents[sku_id]

    @rule(bin_id=a_bin_id, batch_id=a_batch_id, quantity=st.integers(-100, 0))
    def release_batch(self, bin_id, batch_id, quantity):
        rp = self.client.post(
            f"/api/bin/{bin_id}/contents",
            json={
                "id": batch_id,
                "quantity": quantity,
            },
        )
        if quantity + self.model_bins[bin_id].contents.get(batch_id, 0) < 0:
            assert rp.status_code == 405
            assert rp.is_json
            assert rp.json["type"] == "insufficient-quantity"
        else:
            assert rp.status_code == 201
            self.model_bins[bin_id].contents[batch_id] = self.model_bins[bin_id].contents.get(batch_id, 0) + quantity
            if self.model_bins[bin_id].contents[batch_id] == 0:
                del self.model_bins[bin_id].contents[batch_id]

    @rule(source_binId=a_bin_id, destination_binId=a_bin_id, data=st.data())
    def move(self, source_binId, destination_binId, data):
        assume(source_binId != destination_binId)
        # assume(sku_id in self.model_bins[source_binId].contents.keys())
        assume(self.model_bins[source_binId].contents != {})
        sku_id = data.draw(st.sampled_from(list(self.model_bins[source_binId].contents.keys())))
        # assume(quantity >= self.model_bins[source_binId].contents[sku_id])
        quantity = data.draw(st.integers(1, self.model_bins[source_binId].contents[sku_id]))
        rp = self.client.put(
            f"/api/bin/{source_binId}/contents/move",
            json={"id": sku_id, "quantity": quantity, "destination": destination_binId},
        )
        assert rp.status_code == 200
        assert rp.cache_control.no_cache

        self.model_bins[source_binId].contents[sku_id] -= quantity
        self.model_bins[destination_binId].contents[sku_id] = quantity + self.model_bins[
            destination_binId
        ].contents.get(sku_id, 0)
        if self.model_bins[source_binId].contents[sku_id] == 0:
            del self.model_bins[source_binId].contents[sku_id]

    @rule()
    def api_next(self):
        rp = self.client.get("/api/next/bin")
        assert rp.status_code == 200
        assert rp.is_json
        next_bin = rp.json["state"]
        assert next_bin not in self.model_bins.keys()
        assert next_bin.startswith("BIN")
        assert len(next_bin) == 9

        rp = self.client.get("/api/next/sku")
        assert rp.status_code == 200
        assert rp.is_json
        next_sku = rp.json["state"]
        assert next_sku not in self.model_skus.keys()
        assert next_sku.startswith("SKU")
        assert len(next_sku) == 9

        rp = self.client.get("/api/next/batch")
        assert rp.status_code == 200
        assert rp.is_json
        next_batch = rp.json["state"]
        assert next_batch not in self.model_bins.keys()
        assert next_batch.startswith("BAT")
        assert len(next_batch) == 9

    def search_results_generator(self, query):
        def json_to_data_model(in_json_dict):
            if in_json_dict["id"].startswith("BIN"):
                return Bin.from_json(in_json_dict)
            if in_json_dict["id"].startswith("SKU"):
                return Sku.from_json(in_json_dict)
            if in_json_dict["id"].startswith("BAT"):
                return Batch.from_json(in_json_dict)

        starting_from = 0
        while True:
            rp = self.client.get(
                "/api/search",
                query_string={
                    "query": query,
                    "startingFrom": starting_from,
                },
            )
            assert rp.status_code == 200
            assert rp.is_json
            search_state = rp.json["state"]
            for result_json in search_state["results"]:
                yield json_to_data_model(result_json)
            if search_state["starting_from"] + search_state["limit"] > search_state["total_num_results"]:
                break
            else:
                starting_from += search_state["limit"]

    def search_query_matches(self, query, unit):
        STOP_WORDS = "a and the".split()
        terms = query.split()
        if len(terms) != 1:
            pass
        elif query == "" or query in STOP_WORDS:
            return False
        elif query == unit.id:
            return True
        elif hasattr(unit, "owned_codes") and query in unit.owned_codes:
            return True
        elif hasattr(unit, "associate_codes") and query in unit.associated_codes:
            return True
        elif hasattr(unit, "name") and query.casefold() in unit.name.casefold():
            return True
        return False

    # @rule(query=dst.search_query)
    # def search(self, query):
    #     results = list(self.search_results_generator(query))
    #     for unit in it.chain(self.model_bins.values(), self.model_skus.values(), self.model_batches.values()):
    #         if self.search_query_matches(query, unit):
    #             assert unit in results
    #         else:
    #             assert unit not in results

    @rule()
    def search_no_query(self):
        results = list(self.search_results_generator(""))
        assert results == []

    # Safety Invariants

    @invariant()
    def batches_skus_with_same_sku_never_share_bin(self):
        return  # TODO: remove this skipped check
        for bin in self.model_bins.values():
            sku_types = []
            for item_id in bin.contents.values():
                if item_id.startswith("BAT"):
                    sku_type = self.model_batches[item_id].sku_id
                elif item_id.startswith("SKU"):
                    sku_type = item_id
                else:
                    assert False  # bin contents must be Batches or Skus
                if sku_type:
                    assert sku_type not in sku_types  # each sku type should only appear once
                    sku_types.append(sku_type)


TestInventorius = InventoriusStateMachine.TestCase
if os.getenv("HYPOTHESIS_SLOW") == "true":
    TestInventorius.settings = settings(max_examples=10000, stateful_step_count=10, deadline=timedelta(seconds=10))
else:
    TestInventorius.settings = settings(
        max_examples=1000,
        stateful_step_count=10,
        deadline=timedelta(milliseconds=100),
    )
