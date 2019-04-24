import pytest

from hypothesis import given, example
import hypothesis.strategies as hs

from inventory.data_models import Bin, MyEncoder
import tests.data_models_strategies as st
import json

@hs.composite
def bin_and_id(draw,
               ids=hs.integers().map(lambda i: f"BIN{i:08d}")):
    id = draw(ids)
    bin = Bin(id=id, props=draw(st.json))
    return (bin, id)

@given(bin_and_id())
def test_bin_id(bin_id):
    bin, id = bin_id
    assert bin.id == id

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
    
