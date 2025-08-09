from flask import url_for


def operation(rel, method, href, expects_a=None):
    ret = {
        "rel": rel,
        "method": method,
        "href": href,
    }
    if expects_a:
        ret["Expects-a"] = expects_a
    return ret


GET = "GET"
POST = "POST"
PATCH = "PATCH"
PUT = "PUT"
DELETE = "DELETE"
OPTION = "OPTION"
HEAD = "HEAD"


def logout():
    return operation("logout", POST, url_for("user.logout_post"))


def user_delete(id):
    return operation("delete", DELETE, url_for("user.user_delete", id=id))


def batch_create():
    return operation("create", POST, url_for("batch.batches_post"), "Batch patch")


def batch_update(id):
    return operation("update", PATCH, url_for("batch.batch_patch", id=id), "Batch patch")


def batch_delete(id):
    return operation("delete", DELETE, url_for("batch.batch_delete", id=id))


def batch_bins(id):
    return operation("bins", GET, url_for("batch.batch_bins_get", id=id))

def bin_create():
    return operation("create", POST, url_for("bin.bins_post"), "Bin patch")

def bin_update(id):
    return operation("update", PATCH, url_for("bin.bin_patch", id=id), "Bin patch")

def bin_delete(id):
    return operation("delete", DELETE, url_for("bin.bin_delete", id=id))

def sku_create():
    return operation("create", POST, url_for("sku.skus_post"), "Sku patch")

def sku_update(id):
    return operation("update", PATCH, url_for("sku.sku_patch", id=id), "Sku patch")

def sku_delete(id):
    return operation("delete", DELETE, url_for("sku.sku_delete", id=id))

def sku_bins(id):
    return operation("bins", GET, url_for("sku.sku_bins_get", id=id))