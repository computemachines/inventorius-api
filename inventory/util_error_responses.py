from flask import Response, url_for
from json import dumps
from voluptuous import MultipleInvalid, Invalid
from inventory.resource_models import operation

problem_titles = {
    "validation-error": "Input did not validate.",
    "duplicate-resource": "Attempt to create resource that already exists.",
    "missing-resource": "Resource does not exist.",
    "invalid-credentials": "Identity not authorized.",
    "account-deactivated": "Account is deactivated.",
}


def problem_response(status_code=400, json=None):
    resp = Response()
    resp.status_code = status_code
    resp.mimetype = "application/problem+json"
    if json:
        resp.data = dumps(json)
    return resp


def missing_resource_param_error(name, reason=None):
    if type(name) is not list:
        name = [name]
    if reason == None:
        reason = ["Resource does not exist" for _ in name]
    if len(name) != len(reason):
        raise AssertionError("name and reason must have the same shape")
    errors = [Invalid(reason[i], name[i]) for i in range(len(name))]
    return MultipleInvalid(errors)


def invalid_params_response(error: MultipleInvalid, type="validation-error", status_code=400):
    invalid_params = []
    for invalid in error.errors:
        invalid_params.append({"name": invalid.path, "reason": invalid.msg})

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
