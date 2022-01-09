from os import stat
from flask import Response
from json import dumps
from flask.helpers import url_for
from voluptuous import Schema, Required, All, Length, Range
from voluptuous.error import Invalid, MultipleInvalid
from voluptuous.validators import Any
import re


def prefixed_id(prefix=""):
    def must_have_prefix(id):
        if not id.startswith(prefix):
            raise Invalid(f"must start with '{prefix}'")
        return id
    return All(Length(1), str, must_have_prefix)

id_schema = prefixed_id()
password_schema = All(Length(8), str)

def non_empty_string(s):
    if s == "":
        raise Invalid("must not be empty string")
    return s

def non_whitespace(s):
    if re.search('\\s', s):
        raise Invalid(f"must not contain whitespace characters")
    return s

code_list_schema = [All(non_empty_string, non_whitespace)]

# def code_list(codes):
#     if any(re.search('\\s', code) or code == '' for code in codes):
#         raise Invalid(f"")

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

new_batch_schema = Schema({
    Required("id"): prefixed_id("BAT"),
    "owned_codes": code_list_schema,
    "associated_codes": code_list_schema,
    "name": str,
    "props": dict,
    "sku_id": prefixed_id("SKU")
})