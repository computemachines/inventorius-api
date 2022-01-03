from flask import Response, url_for
import json
from flask_login import current_user

from inventory.db import db
from inventory.data_models import UserData

# operation = {
#   "rel": operation name (resource method),
#   "method": GET | POST |PUT|DELETE|PATCH
#   "href": uri,
#   (Expects-a): type or schema
# }

def operation(rel, method, href, expects_a=None):
    ret = {
      "rel": rel,
      "method": method, 
      "href": href,
    }
    if expects_a:
      ret["Expects-a"] = expects_a
    return ret

class PublicProfile:
    @classmethod
    def retrieve_from_id(cls, id):
        profile = PublicProfile()
        profile.id = id
        profile.resourceUri = url_for("user.user_get", id=id)

        private_user_data = UserData.from_mongodb_doc(
            db.users.find_one({"_id": id}))
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
            "Id": self.resourceUri,
            "state": self.state,
            "operations": self.operations,
        })
        return resp


class PrivateProfile:
    @classmethod
    def retrieve_from_id(cls, id):
        profile = PublicProfile()
        profile.id = id
        profile.resourceUri = url_for("user.user_get", id=id)

        private_user_data = UserData.from_mongodb_doc(
            db.users.find_one({"_id": id}))
        profile.state = {
            "id": private_user_data.fixed_id,
            "name": private_user_data.name,
        }
        profile.operations = [
          operation("delete", "DELETE", url_for("user.user_delete", id=id))
        ]
        return profile

    def hypermedia_response(self, status_code=200):
        resp = Response()
        resp.status_code = status_code
        resp.mimetype = "application/json"
        resp.data = json.dumps({
            "Id": self.resourceUri,
            "state": self.state,
            "operations": self.operations,
        })
        return resp
