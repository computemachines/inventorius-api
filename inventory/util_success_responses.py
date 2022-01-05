from flask.helpers import url_for
from inventory.resource_models import HypermediaEndpoint, logout_operation, operation


def login_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        state={"status": "logged in"},
        operations=[logout_operation()]
    ).response(status_code=200)

def logged_out_response():
  return HypermediaEndpoint(
    state={"status": "logged out"}
  ).response(200)

def already_logged_out():
  return HypermediaEndpoint(
    state={"status": "already logged out"}
  ).response(200)

def user_created_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        {"status": "user created"},
    ).response(201)


def user_updated_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        {"status": "user updated"},
    ).response(200)

def user_deleted_response(id):
  return HypermediaEndpoint(
    url_for("user.user_get", id=id),
    {"status": "user deleted"}
  ).response(200)

def bin_deleted_response(id):
  return HypermediaEndpoint(
    url_for("bin.bin_get", id=id),
    {"state": "bin deleted"}
  ).response(200)