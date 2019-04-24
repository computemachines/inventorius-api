from inventory.data_models import Bin, MyEncoder

from hypothesis.strategies import *
from string import printable

printableText = text(printable)
simpleTypes = one_of(none(), integers(), floats(), text(printable))

json = recursive(simpleTypes,
                 lambda children: one_of(
                     dictionaries(text(printable), children),
                     lists(children)))
