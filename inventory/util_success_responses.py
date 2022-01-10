from flask.helpers import url_for
from inventory.resource_models import BatchEndpoint, HypermediaEndpoint
import inventory.resource_operations as operations


def logged_out_response():
    return HypermediaEndpoint(
        state={"status": "logged out"}
    ).get_response(200)


def already_logged_out():
    return HypermediaEndpoint(
        state={"status": "already logged out"}
    ).get_response(200)


def bin_deleted_response(id):
    return HypermediaEndpoint(
        url_for("bin.bin_get", id=id),
        {"status": "bin deleted"}
    ).get_response(200)
