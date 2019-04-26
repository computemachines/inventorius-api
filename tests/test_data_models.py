import pytest

from hypothesis import given, example
import hypothesis.strategies as strat

import sys
print(sys.path)

from inventory.data_models import Bin, MyEncoder
import tests.data_models_strategies as my_strat
import json

@strat.composite
def bin_and_id_props_contents(
        draw,
        ids=strat.integers().map(lambda i: f"BIN{i:08d}")):
    id = draw(ids)
    props = draw(my_strat.json)
    contents = draw(strat.just([]) | strat.none())
    bin = Bin(id=id, props=props, contents=contents)
    return (bin, id, props, contents)

@given(bin_and_id_props_contents())
def test_bin(bin_id_props_contents):
    bin, id, props, contents = bin_id_props_contents
    assert bin.id == id
    assert bin.props == props
    assert bin.contents == contents

    assert json.loads(bin.to_json())['id'] == id
    assert json.loads(bin.to_json()).get('props') == props
    assert json.loads(bin.to_json()).get('contents') == contents

    assert bin.to_mongodb_doc()['id'] == id
    assert bin.to_mongodb_doc().get('props') == props
    assert bin.to_mongodb_doc().get('contents') == None


# def test_bin():
#     bin = Bin({'id': 'BIN000012', 'props': {}})
#     binJson = '{"id": "BIN000012", "props": {}}'

#     assert bin.toJson() == binJson
#     assert json.dumps(bin, cls=MyEncoder) == binJson
#     assert json.dumps([bin], cls=MyEncoder) == '[{}]'.format(binJson)

#     # using generator functions
#     bin = generate_bin("BIN000013")
#     assert bin._id == "BIN000013"
#     assert json.loads(bin.toJson())['id'] == "BIN000013"

# def test_bin_extended():
#     pass
    
# def test_sku():
#     sku = SKU({'id': 'SKU000081',
#                'owned codes': ["SKU000081", "12345678"],
#                'name': 'Op-Amp (Through-Hole) - LM358'})
#     skuJson = '{"id": "SKU000081", "owned codes": ["SKU000081", "12345678"], "name": "Op-Amp (Through-Hole) - LM358"}'

#     assert json.loads(sku.toJson()) == json.loads(skuJson)

# def test_batch():
#     batchJson = {"id": "BATCH0008", }
#     #batch = Batch(json.loads(batchJson))
    
