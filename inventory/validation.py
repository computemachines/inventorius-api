from os import stat
from flask import Response
from json import dumps
from flask.helpers import url_for
from voluptuous import Schema, Required, All, Length, Range
from voluptuous.error import MultipleInvalid

from inventory.resource_models import operation

problem_titles = {
    "validation-error": "Input did not validate.",
    "duplicate-resource": "Attempt to create resource that already exists.",
    "missing-resource": "Resource does not exist.",
    "invalid-credentials": "Identity not authorized."
}


def problem_response(status_code=400, json=None):
    resp = Response()
    resp.status_code = status_code
    resp.mimetype = "application/problem+json"
    if json:
        resp.data = dumps(json)
    return resp


def problem_invalid_params_response(error: MultipleInvalid, type="validation-error"):
    invalid_params = []
    for invalid in error.errors:
        invalid_params.append({"name": invalid.path, "reason": invalid.msg})

    return problem_response(json={
        "type": type,
        "title": problem_titles[type],
        "invalid-params": invalid_params
    })


def problem_duplicate_resource_response(key, reason="must not already exist", status_code=409):
    return problem_response(json={
        "type": "duplicate-resource",
        "title": problem_titles["duplicate-resource"],
        "invalid-params": [{"name": key, "reason": reason}],
    }, status_code=status_code)


def problem_missing_resource_response(uri, create_operation=None):
    return problem_response(status_code=404, json={
        "type": "missing-resource",
        "title": problem_titles["missing-resource"],
        "Id": uri,
        "operations": [create_operation]
    })


def problem_missing_user_response(id):
    return problem_missing_resource_response(
        url_for("user.user_get", id=id), 
        operation("create", "POST", url_for("user.users_post"), "User Patch"))

def problem_bad_username_password_response(name, reason=None):
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

new_user_schema = Schema({
    Required("id"): All(Length(1), str),
    Required("password"): All(Length(8), str),
    Required("name"): str,
})
