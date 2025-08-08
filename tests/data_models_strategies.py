from inventorius.data_models import Bin, Sku, Batch, UserData, Props

from hypothesis import given, example, settings
from hypothesis.strategies import *

from string import ascii_letters, printable, ascii_lowercase, whitespace, digits

import os
import time
import hashlib
import base64

# ids = text(
#     printable.translate(str.maketrans(
#         {"/": None, "?": None, "&": None, "#": None}
#     )).translate(str.maketrans(
#         {c: None for c in whitespace}
#     )), min_size=1)
ids = text(ascii_letters + digits, min_size=1)

fieldNames = text(ascii_lowercase + '_', min_size=1)
# Constrain integers to the 64-bit signed range supported by MongoDB
simpleTypes = one_of(
    none(),
    integers(min_value=-2**63, max_value=2**63 - 1),
    floats(allow_nan=False),
    text(printable),
)

json = recursive(simpleTypes,
                 lambda children: one_of(
                     dictionaries(fieldNames, children),
                     lists(children)),
                 max_leaves=1)

propertyDicts = dictionaries(fieldNames, json)


@composite
def props_(draw):
    props = Props(draw(propertyDicts))

@composite
def label_(draw, prefix, length=9):
    numbers = length - len(prefix)
    return f"{prefix}{draw(integers(0, 10**numbers-1)):0{numbers}d}"


@composite
def bins_(draw, id=None, props=None, contents=None):
    id = id or draw(label_("BIN"))  # f"BIN{draw(integers(0, 6)):06d}"
    props = props or draw(propertyDicts)
    contents = contents or {}
    return Bin(id=id, props=props, contents=contents)


@composite
def skus_(draw, id=None, owned_codes=None, name=None, associated_codes=None, props=None):
    id = id or draw(label_("SKU"))
    owned_codes = owned_codes or draw(lists(text("abc", min_size=1)))
    associated_codes = associated_codes or draw(lists(text("abc", min_size=1)))
    name = name or draw(text("ABC"))
    props = props or draw(propertyDicts)
    return Sku(id=id, owned_codes=owned_codes, name=name, associated_codes=associated_codes, props=props)


@composite
def batches_(draw: DrawFn, id=None, sku_id=0, name=None, owned_codes=None, associated_codes=None, props=None):
    id = id or draw(label_("BAT"))
    if sku_id == 0:
        sku_id = draw(none(), label_("SKU"))
    name = name or draw(text("ABC"))
    owned_codes = owned_codes or draw(lists(text("abc", min_size=1)))
    associated_codes = associated_codes or draw(lists(text("abc", min_size=1)))
    props = props or draw(propertyDicts)
    return Batch(id=id, sku_id=sku_id, name=name, owned_codes=owned_codes, associated_codes=associated_codes, props=props)


@composite
def users_(draw, id=None, name=None, password=None):
    id = id or draw(ids)
    name = name or draw(text())
    password = draw(text(printable, min_size=8))
    # salt = os.urandom(64)
    # derived_shadow_id = hashlib.sha256((str(time.time()) + str(id)).encode("utf-8"),
    #                                    usedforsecurity=False)
    # clipped_shadow_id = base64.encodebytes(
    #     derived_shadow_id.digest()).decode("ascii")[:16]

    # user_data = UserData(
    #     fixed_id=id,
    #     shadow_id=clipped_shadow_id,
    #     password_hash=hashlib.pbkdf2_hmac(
    #         "sha256",
    #         str(password).encode("utf-8"),
    #         salt,
    #         100000),
    #     password_salt=salt,
    #     name=name,
    # )
    return {
        "id": id,
        "name": name,
        "password": password,
    }


search_query = one_of(text(), text("abc", min_size=1), text(
    "ABC", min_size=1), label_("SKU"), label_("BIN"), label_("BAT"))


class DataProxy:
    def __init__(self, *args):
        self.source = list(args)

    def draw(self, wants):
        ret = self.source.pop(0)
        assert type(wants.example()) == type(ret)
        return ret
