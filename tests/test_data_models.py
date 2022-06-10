from inventorius.data_models import Bin, Sku, Batch, Props, DataModelJSONEncoder as Encoder

import pytest
import json
from hypothesis import given, example
from hypothesis.strategies import composite, integers

import tests.data_models_strategies as dst


def test_get_attr():
    batch = Batch(id="BAT1")
    assert hasattr(batch, "id")
    assert batch.sku_id == None


def test_bin_default_contents():
    bin = Bin(contents=None, id='BIN000000', props=None)
    assert json.loads(bin.to_json(mask_default=False)).get('contents') == {}


@given(dst.bins_())
def test_bin(bin):
    assert json.loads(bin.to_json())['id'] == bin.id
    assert json.loads(bin.to_json(mask_default=False)).get('props') == bin.props
    assert json.loads(bin.to_json(mask_default=False)).get('contents') == {}

    bin_jsoned = Bin.from_json(bin.to_json())
    assert bin_jsoned == bin
    assert bin == bin_jsoned

    assert bin.to_mongodb_doc()['_id'] == bin.id
    assert bin.to_mongodb_doc().get('props') == bin.props
    assert bin.to_mongodb_doc().get('contents') == {}


@given(dst.skus_())
def test_sku_equality(original_sku):
    serde1_sku = Sku.from_json(original_sku.to_json())
    serde2_sku = Sku.from_mongodb_doc(original_sku.to_mongodb_doc())

    assert original_sku == serde1_sku
    assert serde1_sku == original_sku
    assert original_sku == serde2_sku
    assert serde2_sku == original_sku
    assert serde1_sku == serde2_sku
    assert original_sku == original_sku


@given(sku1=dst.skus_(), sku2=dst.skus_())
def test_sku_inequality(sku1, sku2):
    if sku1.id != sku2.id:
        assert sku1 != sku2
        assert sku2 != sku1


def test_batch_props():
    new_batch = {
        "id": "BAT0123456",
        "props": {
            "cost_per_case": "12.34"
        }
    }
    batch = Batch.from_json(new_batch)
    print(batch)

def test_batch_no_props():
    batch = Batch(id="BAT0123456")
    print(batch.props)

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
