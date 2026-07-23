import re
from functools import wraps
from json import dumps
from locale import currency
from os import stat

from flask import Response
from flask.helpers import url_for
from voluptuous import ALLOW_EXTRA, All, Length, Range, Required, Schema
from voluptuous.error import Invalid, MultipleInvalid
from voluptuous.validators import Any

CANONICAL_ID_SUFFIX_WIDTH = 6


def normalize_prefixed_id(value, prefix):
    """Return the fixed-width form used for storage, URLs, and QR payloads."""
    if not isinstance(value, str):
        raise Invalid("must be a string")

    value = value.strip().upper()
    match = re.fullmatch(f"{prefix}([0-9]{{1,{CANONICAL_ID_SUFFIX_WIDTH}}})", value)
    if not match:
        raise Invalid(
            f"must start with '{prefix}' followed by at most "
            f"{CANONICAL_ID_SUFFIX_WIDTH} digits"
        )

    return f"{prefix}{match.group(1).zfill(CANONICAL_ID_SUFFIX_WIDTH)}"


def validate_url_id(prefix, param_name="id"):
    """
    Decorator that validates URL path parameters match the expected prefix pattern.

    Prevents MongoDB field traversal attacks by ensuring IDs only contain
    the expected prefix followed by digits (e.g., SKU123, BIN456, BAT789).

    Usage:
        @sku.route('/api/sku/<id>')
        @validate_url_id("SKU")
        def sku_get(id):
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            id_value = kwargs.get(param_name)
            if id_value is not None:
                try:
                    kwargs[param_name] = normalize_prefixed_id(id_value, prefix)
                except Invalid as validation_error:
                    # Import here to avoid circular dependency
                    import inventorius.util_error_responses as problem
                    error = Invalid(
                        validation_error.msg,
                        [param_name]
                    )
                    return problem.invalid_params_response(MultipleInvalid([error]))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def validate_url_user_id(param_name="id"):
    """
    Decorator that validates user ID URL parameters are alphanumeric.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            id_value = kwargs.get(param_name)
            if id_value is not None:
                if not id_value.isalnum() or id_value == "":
                    import inventorius.util_error_responses as problem
                    error = Invalid("must be non-empty alphanumeric", [param_name])
                    return problem.invalid_params_response(MultipleInvalid([error]))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def NoneOr(Else):
    return Any(None, Else)


def prefixed_id(prefix="", matching=None):
    def numeric_with_prefix(id):
        return normalize_prefixed_id(id, prefix)

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


def trimmed_non_empty_string(value: str):
    if not isinstance(value, str):
        raise Invalid("must be a string")
    value = value.strip()
    if not value:
        raise Invalid("must not be blank")
    return value


def trimmed_string(value: str):
    if not isinstance(value, str):
        raise Invalid("must be a string")
    return value.strip()


def positive_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid("must be a number")
    if value <= 0:
        raise Invalid("must be greater than 0")
    return value


def positive_whole_number(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise Invalid("must be a whole number")
    if value <= 0:
        raise Invalid("must be greater than 0")
    return value


def nonnegative_whole_number(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise Invalid("must be a whole number")
    if value < 0:
        raise Invalid("must be at least 0")
    return value


def observed_code(value):
    value = trimmed_non_empty_string(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise Invalid("must not contain control characters")
    return value


def each_unit(value):
    value = trimmed_non_empty_string(value)
    if value != "each":
        raise Invalid("must be 'each' at this stage")
    return value


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
        "id": prefixed_id("BAT"),
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
        "id": prefixed_id("BIN"),
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
        "id": prefixed_id("SKU"),
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

quick_capture_schema = Schema(
    {
        "description": All(trimmed_non_empty_string, Length(max=500)),
        "sku_id": prefixed_id("SKU"),
        Required("bin_id"): prefixed_id("BIN"),
        Required("quantity"): positive_whole_number,
        Required("unit", default="each"): each_unit,
        "observed_codes": All(
            [All(observed_code, Length(max=500))],
            Length(max=50),
        ),
    }
)


def intake_capture_schema(value):
    """Validate one low-friction intake command without guessing its identity."""
    capture = quick_capture_schema(value)
    has_description = "description" in capture
    has_sku_id = "sku_id" in capture
    if has_description == has_sku_id:
        raise MultipleInvalid([Invalid(
            "must provide exactly one of description or sku_id",
            ["description"],
        )])
    return capture


inventory_operation_command_schema = Schema(
    {
        Required("kind"): Any("receive", "transfer", "release"),
        Required("batch_id"): prefixed_id("BAT"),
        Required("quantity"): positive_whole_number,
        Required("unit", default="each"): each_unit,
        # Packaging is deliberately not a command dimension yet.  Requiring
        # null when a client sends the field makes that boundary explicit
        # rather than silently coalescing package identities.
        "packaging_configuration_id": Any(None),
        "location_id": prefixed_id("BIN"),
        "source_location_id": prefixed_id("BIN"),
        "destination_location_id": prefixed_id("BIN"),
        "observed_codes": All(
            [All(observed_code, Length(max=500))],
            Length(max=50),
        ),
    }
)


inventory_correction_command_schema = Schema(
    {
        Required("quantity"): All(
            nonnegative_whole_number,
            # Keep correction input exactly representable by browser clients
            # and comfortably inside MongoDB Decimal128. Receipt reads still
            # render larger historical exact values as strings.
            Range(max=9_007_199_254_740_991),
        ),
        Required("location_id"): prefixed_id("BIN"),
    }
)


PROCESS_DEFINITION_KINDS = (
    "repackaging",
    "assembly",
    "disassembly",
    "transformation",
    "blending",
)

process_requirement_schema = Schema(
    {
        Required("role"): All(trimmed_non_empty_string, Length(max=120)),
        "sku_id": NoneOr(prefixed_id("SKU")),
        "quantity": NoneOr(positive_number),
        Required("unit", default="each"): All(
            trimmed_non_empty_string,
            Length(max=40),
        ),
    }
)

process_requirements_schema = All(
    [process_requirement_schema],
    Length(min=1, max=50),
)

process_instructions_schema = All(
    [All(trimmed_non_empty_string, Length(max=500))],
    Length(max=100),
)

process_definition_create_schema = Schema(
    {
        Required("name"): All(trimmed_non_empty_string, Length(max=200)),
        Required("kind"): Any(*PROCESS_DEFINITION_KINDS),
        Required("inputs"): process_requirements_schema,
        Required("outputs"): process_requirements_schema,
        "description": All(trimmed_string, Length(max=2000)),
        "instructions": process_instructions_schema,
    }
)

process_definition_patch_schema = Schema(
    {
        "name": All(trimmed_non_empty_string, Length(max=200)),
        "kind": Any(*PROCESS_DEFINITION_KINDS),
        "inputs": process_requirements_schema,
        "outputs": process_requirements_schema,
        "description": All(trimmed_string, Length(max=2000)),
        "instructions": process_instructions_schema,
    }
)
