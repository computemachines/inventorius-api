from os import stat
from flask import Response
from json import dumps
from flask.helpers import url_for
from voluptuous import Schema, Required, All, Length, Range
from voluptuous.error import Invalid, MultipleInvalid
from voluptuous.validators import Any
import re


def NoneOr(Else):
    return Any(None, Else)


def prefixed_id(prefix="", matching=None):
    def numeric_with_prefix(id):
        if not re.match(f"^{prefix}[0-9]+$", id):
            raise Invalid(f"must start with '{prefix}' followed by digits")
        return id

    # def must_have_prefix(id):
    #     if not id.startswith(prefix):
    #         raise Invalid(f"must start with '{prefix}'")
    #     return id,

    # def numeric_suffix(id):
    #     if id[len(prefix):].isdigit():
    #         return id
    #     raise Invalid(f"must have numeric suffix")
    if matching:
        return All(str, numeric_with_prefix, matching)
    else:
        return All(str, numeric_with_prefix)



def non_empty_string(s):
    if s == "":
        raise Invalid("must not be empty string")
    return s


def non_whitespace(s):
    if re.search('\\s', s):
        raise Invalid(f"must not contain whitespace characters")
    return s



id_schema = All(Length(1), str, non_empty_string, non_whitespace)
password_schema = All(Length(8), str)
code_list_schema = [All(non_empty_string, non_whitespace)]

# def code_list(codes):
#     if any(re.search('\\s', code) or code == '' for code in codes):
#         raise Invalid(f"")

forced_schema = Schema({
    "force": "true"
})

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

batch_patch_schema = Schema({
    Required("id"): prefixed_id("BAT"),
    "owned_codes": NoneOr(code_list_schema),
    "associated_codes": NoneOr(code_list_schema),
    "name": NoneOr(str),
    "props": NoneOr(dict),
    "sku_id": NoneOr(prefixed_id("SKU")),
})

new_bin_schema = Schema({
    Required("id"): prefixed_id("BIN"),
    "props": dict,
})


bin_patch_schema = Schema({
    Required("id"): prefixed_id("BIN"),
    "props": NoneOr(dict),
})

new_sku_schema = Schema({
    Required("id"): prefixed_id("SKU"),
    "owned_codes": code_list_schema,
    "associated_codes": code_list_schema,
    "name": str,
    "props": dict,
})

sku_patch_schema = Schema({
    Required("id"): prefixed_id("SKU"),
    "owned_codes": NoneOr(code_list_schema),
    "associated_codes": NoneOr(code_list_schema),
    "name": NoneOr(str),
    "props": NoneOr(dict),
})
