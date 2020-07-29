from inventory.data_models import Bin, Sku

from hypothesis import given, example, settings
from hypothesis.strategies import *

from string import printable, ascii_lowercase

fieldNames_ = text(ascii_lowercase+'_')
simpleTypes_ = one_of(none(),
                      integers(min_value=-2**63, max_value=2**63),
                      floats(allow_nan=False), text(printable))

json_ = recursive(simpleTypes_,
                  lambda children: one_of(
                      dictionaries(fieldNames_, children),
                      lists(children)),
                  max_leaves=1)


@composite
def bins_(draw, id=None, props=None, contents=None):
    id = id or f"BIN{draw(integers(0, 10)):08d}"
    props = props or draw(json_)
    return Bin(id=id, props=props)


@composite
def skus_(draw, id=None, owned_codes=None, name=None):
    id = id or f"SKU{draw(integers(0, 10)):08d}"
    owned_codes = owned_codes or draw(lists(text("abc")))
    name = draw(text("ABC"))
    return Sku(id=id, owned_codes=owned_codes, name=name)


@composite
def batches_(draw, id=None, sku_id=None):
    id = id or f"BAT{draw(integers(0, 10)):08d}"
    sku_id = sku_id or f"SKU{draw(integers(0, 100)):08d}"
    return Batch(id=id, sku_id=sku_id)
