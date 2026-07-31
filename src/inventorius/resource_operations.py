from flask import url_for


_UNSET = object()


def schema(name, version=1):
    return {"name": name, "version": version}


def required_creation_idempotency():
    return {
        "mode": "required",
        "key": {
            "in": "header",
            "name": "Idempotency-Key",
            "max_length": 200,
        },
        "scope": "resource-creation",
        "replay": "return-committed-result",
        "mismatch": "conflict",
    }


def operation(
    rel,
    method,
    href,
    expects_a=None,
    *,
    kind=_UNSET,
    request_schema=_UNSET,
    response_schema=_UNSET,
    idempotency=_UNSET,
):
    ret = {
        "rel": rel,
        "method": method,
        "href": href,
    }
    if expects_a:
        ret["Expects-a"] = expects_a
    typed_fields = (kind, request_schema, response_schema, idempotency)
    if any(field is not _UNSET for field in typed_fields):
        if not all(field is not _UNSET for field in typed_fields):
            raise ValueError("typed operation descriptors require every typed field")
        ret.update({
            "kind": kind,
            "request_schema": request_schema,
            "response_schema": response_schema,
            "idempotency": idempotency,
        })
    return ret


GET = "GET"
POST = "POST"
PATCH = "PATCH"
PUT = "PUT"
DELETE = "DELETE"
OPTION = "OPTION"
HEAD = "HEAD"


def batch_create(rel="create"):
    return operation(
        rel,
        POST,
        url_for("batch.batches_post"),
        "Batch patch",
        kind="catalog.batch.create",
        request_schema=schema("inventorius.batch-create"),
        response_schema=schema("inventorius.batch-creation-result"),
        idempotency=required_creation_idempotency(),
    )


def batch_update(id):
    return operation(
        "update",
        PATCH,
        url_for("batch.batch_patch", id=id),
        "Batch patch",
        kind="catalog.batch.update",
        request_schema=schema("inventorius.batch-patch"),
        response_schema=schema("inventorius.operation-status"),
        idempotency={"mode": "not-supported"},
    )


def batch_delete(id):
    return operation(
        "delete",
        DELETE,
        url_for("batch.batch_delete", id=id),
        kind="catalog.batch.delete",
        request_schema=None,
        response_schema=schema("inventorius.operation-status"),
        idempotency={"mode": "not-supported"},
    )


def batch_bins(id):
    return operation(
        "bins",
        GET,
        url_for("batch.batch_bins_get", id=id),
        kind="catalog.batch.locations.read",
        request_schema=None,
        response_schema=schema("inventorius.batch-locations"),
        idempotency={"mode": "not-applicable"},
    )


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
