from os import stat
from flask import Response
from json import dumps
from flask.helpers import url_for
from voluptuous import Schema, Required, All, Length, Range
from voluptuous.error import MultipleInvalid

from inventory.resource_models import operation

id_schema = All(Length(1), str)
password_schema = All(Length(8), str)

new_user_schema = Schema({
    Required("id"): id_schema,
    Required("password"): password_schema,
    Required("name"): str,
})

user_patch_schema = Schema({
    "password": password_schema,
    "name": str,
})

login_request_schema = Schema({
    Required("id"): id_schema,
    Required("password"): password_schema,
})