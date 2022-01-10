from flask import Response, url_for
import json
from flask_login import current_user

from inventory.db import db
from inventory.data_models import UserData, Batch
import inventory.resource_operations as operations

# operation = {
#   "rel": operation name (resource method),
#   "method": GET | POST |PUT|DELETE|PATCH
#   "href": uri,
#   (Expects-a): type or schema
# }


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
            data["state"] = self.state
        if self.operations is not None:
            data["operations"] = self.operations

        resp.data = json.dumps(data)
        return resp
    
    def redirect_response(self, redirect=True):
        if redirect:
            raise NotImplementedError()
        resp = Response()
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps({"Id": self.resource_uri})
        return resp

class PublicProfile:
    @classmethod
    def retrieve_from_id(cls, id):
        profile = PublicProfile()
        profile.id = id
        profile.resource_uri = url_for("user.user_get", id=id)

        private_user_data = UserData.from_mongodb_doc(
            db.user.find_one({"_id": id}))
        if not private_user_data:
            return None
        profile.state = {
            "id": private_user_data.fixed_id,
            "name": private_user_data.name,
        }
        profile.operations = []
        return profile

    def hypermedia_response(self, status_code=200):
        resp = Response()
        resp.status_code = status_code
        resp.mimetype = "application/json"
        resp.data = json.dumps({
            "Id": self.resource_uri,
            "state": self.state,
            "operations": self.operations,
        })
        return resp


class PrivateProfile:
    @classmethod
    def retrieve_from_id(cls, id):
        profile = PublicProfile()
        profile.id = id
        profile.resource_uri = url_for("user.user_get", id=id)

        private_user_data = UserData.from_mongodb_doc(
            db.user.find_one({"_id": id}))
        if not private_user_data:
            return None
        profile.state = {
            "id": private_user_data.fixed_id,
            "name": private_user_data.name,
            "secret": "info",
        }
        profile.operations = [
            operations.user_delete(id)
        ]
        return profile

    def hypermedia_response(self, status_code=200):
        resp = Response()
        resp.status_code = status_code
        resp.mimetype = "application/json"
        resp.data = json.dumps({
            "Id": self.resource_uri,
            "state": self.state,
            "operations": self.operations,
        })
        return resp


class BatchEndpoint(HypermediaEndpoint):
    def __init__(self, data_batch: Batch):
        self.data_batch = data_batch
        super().__init__(
            resource_uri=url_for("batch.batch_get", id=data_batch.id),
            state=data_batch.to_dict(),
            operations=[
                operations.batch_update(id),
                operations.batch_delete(id),
                operations.batch_bins(id),
            ],
        )
