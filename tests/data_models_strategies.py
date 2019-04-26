from inventory.data_models import Bin, MyEncoder

from hypothesis.strategies import *
from string import printable, ascii_lowercase

fieldNames = text(ascii_lowercase+'_')
simpleTypes = one_of(none(),
                     integers(),
                     floats(allow_nan=False), text(printable))

json = recursive(simpleTypes,
                 lambda children: one_of(
                     dictionaries(fieldNames, children),
                     lists(children)))
