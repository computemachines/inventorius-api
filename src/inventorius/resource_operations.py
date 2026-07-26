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


def batch_create():
    return operation("create", POST, url_for("batch.batches_post"), "Batch patch")


def batch_update(id):
    return operation("update", PATCH, url_for("batch.batch_patch", id=id), "Batch patch")


def batch_delete(id):
    return operation("delete", DELETE, url_for("batch.batch_delete", id=id))


def batch_bins(id):
    return operation("bins", GET, url_for("batch.batch_bins_get", id=id))


def process_definition_create():
    return operation(
        "create",
        POST,
        url_for("process_definition.process_definitions_post"),
        "Process definition",
    )


def process_definition_update(id):
    return operation(
        "update",
        PATCH,
        url_for("process_definition.process_definition_patch", id=id),
        "Process definition patch",
    )


def process_definition_delete(id):
    return operation(
        "delete",
        DELETE,
        url_for("process_definition.process_definition_delete", id=id),
    )


def process_definition_revisions(id):
    return operation(
        "revisions",
        GET,
        url_for("process_definition.process_definition_revisions_get", id=id),
    )

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

def sku_batches(id):
    return operation("batches", GET, url_for("sku.sku_batches_get", id=id))
