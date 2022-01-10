from flask.helpers import url_for
from inventory.resource_models import HypermediaEndpoint
import inventory.resource_operations as operations


def login_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        state={"status": "logged in"},
        operations=[operations.logout()]
    ).get_response(status_code=200)


def logged_out_response():
    return HypermediaEndpoint(
        state={"status": "logged out"}
    ).get_response(200)


def already_logged_out():
    return HypermediaEndpoint(
        state={"status": "already logged out"}
    ).get_response(200)

# CRUD ----- CREATE


def user_created_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        {"status": "user created"},
    ).get_response(201)


def batch_created_response(id):
    return HypermediaEndpoint(
        url_for("batch.batch_get", id=id),
        {"status": "batch created"}
    ).get_response(201)

# CRUD ----- UPDATE


def user_updated_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        {"status": "user updated"},
    ).get_response(200)

# CRUD ----- DELETE


def user_deleted_response(id):
    return HypermediaEndpoint(
        url_for("user.user_get", id=id),
        {"status": "user deleted"}
    ).get_response(200)


def bin_deleted_response(id):
    return HypermediaEndpoint(
        url_for("bin.bin_get", id=id),
        {"state": "bin deleted"}
    ).get_response(200)
