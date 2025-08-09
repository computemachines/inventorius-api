from flask import Response, url_for
import json
from flask_login import current_user
from flask_login.utils import encode_cookie

from inventorius.db import db
from inventorius.data_models import DataModel, DataModelJSONEncoder, UserData, Batch, Bin
import inventorius.resource_operations as operations

# operation = {
#   "rel": operation name (resource method),
#   "method": GET | POST |PUT|DELETE|PATCH
#   "href": uri,
#   (Expects-a): type or schema
# }


class BlankEncoder(json.JSONEncoder):
    """Without this blank encoder the 'dumps' in problem_response and get_response throws error when encountering unserializable types."""
    def default(self, o):
        return {}


class HypermediaEndpoint:
    def __init__(self, resource_uri=None, state=None, operations=None):
        self.resource_uri = resource_uri
        self.state = state
        self.operations = operations

    def get_response(self, status_code=200, mimetype="application/json"):
        resp = Response()
        resp.status_code = status_code
        resp.mimetype = mimetype

        data = {}
        if self.resource_uri is not None:
            data["Id"] = self.resource_uri
        if self.state is not None:
            if isinstance(self.state, DataModel):
                data["state"] = self.state.to_dict(mask_default=True)
            else:
                data["state"] = self.state
        if self.operations is not None:
            data["operations"] = self.operations

        resp.data = json.dumps(data, cls=BlankEncoder)
        return resp

    def redirect_response(self, redirect=True):
        if redirect:
            raise NotImplementedError()
        resp = Response()
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps({"Id": self.resource_uri})
        return resp

    def status_response(self, status_message="ok", status_code=200):
        resp = Response()
        resp.status_code = status_code
        resp.mimetype = "application/json"
        resp.data = json.dumps(
            {"Id": self.resource_uri, "status": status_message})
        return resp


class Profile(HypermediaEndpoint):
    @classmethod
    def from_user_data(cls, user_data: UserData):
        if not user_data:
            return None
        profile = Profile(
            resource_uri=url_for("user.user_get", id=user_data.fixed_id),
            state={
                "id": user_data.fixed_id,
                "name": user_data.name,
            },
            operations=[]
        )
        profile.user_id = user_data.fixed_id
        profile.user_data = user_data
        return profile

    @classmethod
    def from_id(cls, user_id: str, retrieve=False):
        if retrieve:
            return cls.from_user_data(cls._retrieve(user_id))
        else:
            profile = Profile(
                resource_uri=url_for("user.user_get", id=user_id),
                operations=[]
            )
            profile.user_id = user_id
            return profile

    @classmethod
    def _retrieve(cls, user_id):
        return UserData.from_mongodb_doc(
            db.user.find_one({"_id": user_id}))

    def login_success_response(self):
        return self.status_response("logged in")

    def created_success_response(self):
        return self.status_response("user created", status_code=201)

    def updated_success_response(self):
        return self.status_response("user updated")

    def deleted_success_response(self):
        return self.status_response("user deleted")


class PrivateProfile(Profile):
    @classmethod
    def from_user_data(cls, user_data: UserData):
        profile = super().from_user_data(user_data)
        if not profile:
            return None
        profile.state['secret'] = profile.user_data.shadow_id
        return profile

    @classmethod
    def from_id(cls, user_id: str, retrieve=False):
        profile = super().from_id(user_id, retrieve=retrieve)
        if not profile:
            return None
        profile.operations = [
            operations.user_delete(user_id)
        ]
        return profile


class BatchEndpoint(HypermediaEndpoint):
    @classmethod
    def from_batch(cls, data_batch: Batch):
        endpoint = BatchEndpoint(
            resource_uri=url_for("batch.batch_get", id=data_batch.id),
            state=data_batch.to_dict(mask_default=True),
            operations=[
                operations.batch_update(data_batch.id),
                operations.batch_delete(data_batch.id),
                operations.batch_bins(data_batch.id),
            ],
        )
        endpoint.data_batch = data_batch
        return endpoint

    @classmethod
    def from_id(cls, batch_id: str, retrieve=False):
        if retrieve:
            raise NotImplementedError()

        endpoint = BatchEndpoint(
            resource_uri=url_for("batch.batch_get", id=batch_id),
            operations=[
                operations.batch_update(batch_id),
                operations.batch_delete(batch_id),
                operations.batch_bins(batch_id),
            ],
        )
        return endpoint

    def created_success_response(self):
        return self.status_response("batch created", status_code=201)

    def updated_success_response(self):
        return self.status_response("batch updated")

    def deleted_success_response(self):
        return self.status_response("batch deleted")


class BatchBinsEndpoint(HypermediaEndpoint):
    @classmethod
    def from_id(cls, batch_id, retrieve=False):
        if not retrieve:
            raise NotImplementedError()

        contained_by_bins = [
            Bin.from_mongodb_doc(bson)
            for bson in db.bin.find({
                f"contents.{batch_id}": {"$exists": True}
            })]
        locations = {bin.id: {batch_id: bin.contents[batch_id]}
                     for bin in contained_by_bins}

        endpoint = BatchBinsEndpoint(
            resource_uri=url_for("batch.batch_bins_get", id=batch_id),
            state=locations
        )
        return endpoint


class BinEndpoint(HypermediaEndpoint):
    @classmethod
    def from_bin(cls, bin):
        endpoint = BinEndpoint(
            resource_uri=url_for("bin.bin_get", id=bin.id),
            state=bin.to_dict(),
            operations=[
                operations.bin_update(bin.id),
                operations.bin_delete(bin.id),
            ]
        )
        return endpoint

    def created_success_response(self):
        return self.status_response("bin created", status_code=201)

    def updated_success_response(self):
        return self.status_response("bin updated")

    def deleted_success_response(self):
        return self.status_response("bin deleted")


class SkuEndpoint(HypermediaEndpoint):
    @classmethod
    def from_sku(cls, sku):
        endpoint = SkuEndpoint(
            resource_uri=url_for("sku.sku_get", id=sku.id),
            state=sku.to_dict(),
            operations=[
                operations.sku_update(sku.id),
                operations.sku_delete(sku.id),
                operations.sku_bins(sku.id),
            ]
        )
        return endpoint

    def created_success_response(self):
        return self.status_response("sku created", status_code=201)

    def updated_success_response(self):
        return self.status_response("sku updated")

    def deleted_success_response(self):
        return self.status_response("sku deleted")


class StatusEndpoint(HypermediaEndpoint):
    def __init__(self, version, is_up=True):
        super().__init__(resource_uri=url_for("get_version"),
                         state={"version": version, "is-up": is_up})
