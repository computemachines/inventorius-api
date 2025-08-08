import re
from json import dumps
from locale import currency
from os import stat

from flask import Response
from flask.helpers import url_for
from voluptuous import ALLOW_EXTRA, All, Length, Range, Required, Schema
from voluptuous.error import Invalid, MultipleInvalid
from voluptuous.validators import Any


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
    if re.search("\\s", s):
        raise Invalid(f"must not contain whitespace characters")
    return s


def alphanum(s: str):
    if not s.isalnum():
        raise Invalid("must be alphanumeric")
    return s


def positive(i: int):
    if i <= 0:
        raise Invalid("must be greater than or equal to 1")
    return i


def str_dec(s):
    if type(s) is not str:
        raise Invalid("must be a string")
    if not (re.search(r"^[+-]?(\d*\.)?\d*$", s) or re.search(r"\d", s)):
        raise Invalid("must be a decimal string")
    return s


id_schema = All(Length(1), str, non_empty_string, non_whitespace, alphanum)
password_schema = All(Length(8), str)
code_list_schema = [All(non_empty_string, non_whitespace)]

# def code_list(codes):
#     if any(re.search('\\s', code) or code == '' for code in codes):
#         raise Invalid(f"")

forced_schema = Schema({"force": "true"})

new_user_schema = Schema(
    {
        Required("id"): id_schema,
        Required("password"): password_schema,
        Required("name"): str,
    }
)

user_patch_schema = Schema(
    {
        "password": password_schema,
        "name": str,
    }
)

login_request_schema = Schema(
    {
        Required("id"): id_schema,
        Required("password"): password_schema,
    }
)

units_schema = Schema(
    {
        Required("unit"): str,
        Required("value"): Any(int, float),
        "exponent": int,
    }
)


def base_unit(unit):
    return units_schema.extend(
        {
            Required("unit"): unit,
        }
    )


currency = base_unit("USD")

props_schema = Schema(
    {
        "cost_per_case": currency,
        "original_cost_per_case": currency,
        "count_per_case": int,
        "original_count_per_case": int,
    },
    extra=ALLOW_EXTRA,
)

new_batch_schema = Schema(
    {
        Required("id"): prefixed_id("BAT"),
        "owned_codes": code_list_schema,
        "associated_codes": code_list_schema,
        "name": str,
        "props": props_schema,
        "sku_id": NoneOr(prefixed_id("SKU")),
    }
)

batch_patch_schema = Schema(
    {
        Required("id"): prefixed_id("BAT"),
        "owned_codes": NoneOr(code_list_schema),
        "associated_codes": NoneOr(code_list_schema),
        "name": NoneOr(str),
        "props": NoneOr(props_schema),
        "sku_id": NoneOr(prefixed_id("SKU")),
    }
)

new_bin_schema = Schema(
    {
        Required("id"): prefixed_id("BIN"),
        "props": props_schema,
    }
)


bin_patch_schema = Schema(
    {
        Required("id"): prefixed_id("BIN"),
        "props": NoneOr(props_schema),
    }
)

new_sku_schema = Schema(
    {
        Required("id"): prefixed_id("SKU"),
        "owned_codes": code_list_schema,
        "associated_codes": code_list_schema,
        "name": str,
        "props": props_schema,
    }
)

sku_patch_schema = Schema(
    {
        Required("id"): prefixed_id("SKU"),
        "owned_codes": NoneOr(code_list_schema),
        "associated_codes": NoneOr(code_list_schema),
        "name": NoneOr(str),
        "props": NoneOr(props_schema),
    }
)

item_move_schema = Schema(
    {
        Required("id"): Any(prefixed_id("SKU"), prefixed_id("BAT")),
        Required("destination"): prefixed_id("BIN"),
        Required("quantity"): All(int, positive),
    }
)

item_release_receive_schema = Schema(
    {
        Required("id"): Any(prefixed_id("SKU"), prefixed_id("BAT")),
        Required("quantity"): int,  # can be positive or negative
    }
)
