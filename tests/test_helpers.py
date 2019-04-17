import pytest

from inventory.helpers import Bin, MyEncoder
import json

def test_bin_to_json():
    bin = Bin({'id': 'BIN000012', 'props': {}})
    binJson = '{"id": "BIN000012", "props": {}}'

    assert bin.toJson() == binJson
    assert json.dumps(bin, cls=MyEncoder) == binJson
    assert json.dumps([bin], cls=MyEncoder) == '[{}]'.format(binJson)
