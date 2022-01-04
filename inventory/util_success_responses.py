from flask.helpers import url_for
from inventory.resource_models import HypermediaEndpoint, logout_operation, operation


def login_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        state={"status": "logged in"},
        operations=[logout_operation()]
    ).response(status_code=204)

def user_created_response(id):
  return HypermediaEndpoint(
    url_for("user.user_get", id=id),
    {"status": "user created"},
  ).response(201)

def user_updated_response(id):
    return HypermediaEndpoint(
    url_for("user.user_get", id=id),
    {"status": "user updated"},
  ).response(204)