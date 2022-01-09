from flask.helpers import url_for
from inventory.resource_models import HypermediaEndpoint
from inventory.resource_operations import operation
import inventory.resource_operations as operations


def login_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        state={"status": "logged in"},
        operations=[operation.logout()]
    ).response(status_code=200)


def logged_out_response():
    return HypermediaEndpoint(
        state={"status": "logged out"}
    ).response(200)


def already_logged_out():
    return HypermediaEndpoint(
        state={"status": "already logged out"}
    ).response(200)

# CRUD ----- CREATE


def user_created_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        {"status": "user created"},
    ).response(201)


def batch_created_response(id):
    return HypermediaEndpoint(
        url_for("batch.batch_get", id=id),
        {"status": "batch created"}
    ).response(201)

# CRUD ----- UPDATE


def user_updated_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        {"status": "user updated"},
    ).response(200)

# CRUD ----- DELETE


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
