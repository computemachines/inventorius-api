from flask import Response, url_for
from json import dumps
from voluptuous import MultipleInvalid, Invalid
from inventory.resource_operations import operation
import inventory.resource_operations as operations

problem_titles = {
    "validation-error": "Input did not validate.",
    "duplicate-resource": "Attempt to create resource that already exists.",
    "missing-resource": "Resource does not exist.",
    "invalid-credentials": "Identity not authorized.",
    "account-deactivated": "Account is deactivated.",
    "dangerous-operation": "This operation requires force=true."
}


def problem_response(status_code=400, json=None):
    resp = Response()
    resp.status_code = status_code
    if json:
        resp.mimetype = "application/problem+json"
        resp.data = dumps(json)

    return resp


def missing_resource_param_error(name, reason=None):
    if isinstance(name, list) or isinstance(reason, list):
        if not (isinstance(name, list) and isinstance(reason, list)):
            raise AssertionError("name and reason must have same type")
        if len(name) != len(reason):
            raise AssertionError(
                "name and reason must have the same list length")
    if type(name) is not list:
        name = [name]
    if not isinstance(reason, list):
        reason = [reason]
    if reason == None:
        reason = ["Resource does not exist" for _ in name]
    errors = [Invalid(reason[i], name[i]) for i in range(len(name))]
    return MultipleInvalid(errors)


def invalid_params_response(error: MultipleInvalid, type="validation-error", status_code=400):
    invalid_params = []
    for invalid in error.errors:
        name = invalid.path
        if isinstance(name, list):
            name = name[0]
        invalid_params.append({"name": name, "reason": invalid.msg})

    return problem_response(
        json={
            "type": type,
            "title": problem_titles[type],
            "invalid-params": invalid_params
        },
        status_code=status_code)


def duplicate_resource_response(key, reason="must not already exist", status_code=409):
    return problem_response(json={
        "type": "duplicate-resource",
        "title": problem_titles["duplicate-resource"],
        "invalid-params": [{"name": key, "reason": reason}],
    }, status_code=status_code)


def missing_resource_response(uri, create_operation=None):
    return problem_response(status_code=404, json={
        "type": "missing-resource",
        "title": problem_titles["missing-resource"],
        "Id": uri,
        "operations": [create_operation]
    })


def missing_user_response(id):
    return missing_resource_response(
        url_for("user.user_get", id=id),
        operation("create", "POST", url_for("user.users_post"), "User Patch"))


def missing_bin_response(id):
    return missing_resource_response(
        url_for("bin.bin_get", id=id),
        operations.bin_create()
    )


def missing_batch_response(id):
    return missing_resource_response(
        url_for("batch.batch_get", id=id),
        operations.batch_create(),
    )


def missing_sku_response(id):
    return missing_resource_response(
        url_for("sku.sku_get", id=id),
        operations.sku_create()
    )


def bad_username_password_response(name, reason=None):
    if name == "id" and reason == None:
        reason = "Id does not exist"
    if name == "password" and reason == None:
        reason = "Incorrect password"
    return problem_response(
        status_code=401,
        json={
            "type": "invalid-credentials",
            "title": problem_titles["invalid-credentials"],
            "invalid-params": [{"name": name, reason: reason or ""}]
        }
    )


def deactivated_account(id):
    return problem_response(
        status_code=401,
        json={
            "type": "account-deactivated",
            "title": problem_titles["account-deactivated"],
            "Id": url_for("user.user_get", id=id)
        })


def dangerous_operation_unforced_response(name=None, reason=""):
    """
    name <== the param that requires force=True
    reason <== human readable explanation of why force=True is necessary
    """
    force_reason = "force must be set to true"
    if name:
        force_reason = force_reason + ", or invalid parameter " + name + " must be resolved"

    invalid_params = [{
        "name": "force",
        "reason": force_reason
    }]

    if name:
        invalid_params.append({
            "name": name,
            "reason": reason
        })

    return problem_response(
        status_code=405,
        json={
            "type": "dangerous-operation",
            "title": problem_titles["dangerous-operation"],
            "invalid-params": invalid_params
        }
    )
