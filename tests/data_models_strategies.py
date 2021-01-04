from inventory.data_models import Bin, Sku, Batch

from hypothesis import given, example, settings
from hypothesis.strategies import *

from string import printable, ascii_lowercase

fieldNames_ = text(ascii_lowercase+'_')
simpleTypes_ = one_of(none(),
                      integers(min_value=-2**63, max_value=2**63),
                      floats(allow_nan=False), text(printable))

json = recursive(simpleTypes_,
                 lambda children: one_of(
                     dictionaries(fieldNames_, children),
                     lists(children)),
                 max_leaves=1)


@composite
def label_(draw, prefix, length=9):
    numbers = length - len(prefix)
    return f"{prefix}{draw(integers(0, 10**numbers-1)):0{numbers}d}"


@composite
def bins_(draw, id=None, props=None, contents=None):
    id = id or draw(label_("BIN"))  # f"BIN{draw(integers(0, 6)):06d}"
    props = props or draw(json)
    return Bin(id=id, props=props)


@composite
def skus_(draw, id=None, owned_codes=None, name=None, associated_codes=None, props=None):
    id = id or f"SKU{draw(integers(0, 10)):06d}"
    owned_codes = owned_codes or draw(lists(text("abc")))
    associated_codes = associated_codes or draw(lists(text("abc")))
    name = name or draw(text("ABC"))
    # props = props or draw(json())
    return Sku(id=id, owned_codes=owned_codes, name=name, associated_codes=associated_codes, props=props)


@composite
def batches_(draw, id=None, sku_id=None):
    id = id or f"BAT{draw(integers(0, 10)):06d}"
    sku_id = sku_id or f"SKU{draw(integers(0, 100)):06d}"
    if draw(booleans()):
        return Batch(id=id, sku_id=sku_id)
    else:
        return Batch(id=id)
