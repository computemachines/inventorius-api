from flask.helpers import url_for
from inventorius.resource_models import BatchEndpoint, HypermediaEndpoint
import inventorius.resource_operations as operations


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

def moved_response():
    return HypermediaEndpoint(
        state={"status": "items moved"}
    ).get_response(200)

def bin_contents_post_response(quantity):
    if quantity > 0:
        status = "items received"
    if quantity < 0:
        status = "items released"
    if quantity == 0:
        status = "no change"
    return HypermediaEndpoint(
        state={"status": status}
    ).get_response(201)