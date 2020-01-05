import pytest

from hypothesis import given, example
import hypothesis.strategies as strat

import sys
print(sys.path)

from inventory.data_models import Bin, MyEncoder
import tests.data_models_strategies as my_strat
import json

@strat.composite
def bin_and_id_props(
        draw,
        ids=strat.integers().map(lambda i: f"BIN{i:08d}")):
    id = draw(ids)
    props = draw(my_strat.json)
    bin = Bin(id=id, props=props)
    return (bin, id, props)

@given(bin_and_id_props())
def test_bin(bin_id_props):
    bin, id, props = bin_id_props
    assert bin.id == id
    assert bin.props == props
    assert bin.contents == []

    assert bin == bin
    assert Bin(id="A") != Bin(id="B")
    assert not(Bin(id="A") == Bin(id="B"))

    assert json.loads(bin.to_json())['id'] == id
    assert json.loads(bin.to_json()).get('props') == props
    assert json.loads(bin.to_json()).get('contents') == []

    bin_jsoned = Bin.from_json(bin.to_json())
    assert bin_jsoned == bin
    assert bin == bin_jsoned

    print(bin)

    assert bin.to_mongodb_doc()['id'] == id
    assert bin.to_mongodb_doc().get('props') == props
    assert bin.to_mongodb_doc().get('contents') == []

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
    
