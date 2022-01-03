from flask import Response
import json
from voluptuous import Schema, Required, All, Length, Range
from voluptuous.error import MultipleInvalid

problem_titles = {
    "validation-error": "Input did not validate."
}


def problem_response(status_code=400, json=None):
    resp = Response()
    resp.status_code = status_code
    resp.mimetype = "application/problem+json"
    if json:
        resp.data = json.dumps(json)
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


def problem_duplicate_resource_response(key, reason="must not already exist"):
    return problem_response(json={
        "type": "duplicate-resource",
        "title": problem_titles["duplicate-resource"],
        "invalid-params": [{"name": key, "reason": reason}],
    })


new_user_schema = Schema({
    Required("id"): All(Length(1), str),
    Required("password"): All(Length(8), str),
    Required("name"): str,
})
