from inventory.data_models import Bin, Sku, Uniq, Batch

bin1 = Bin(id="BIN1")
bin2 = Bin(id="BIN2")
sku1 = Sku(id="SKU1")
uniq1 = Uniq(id="UNIQ1", bin_id=bin1.id)


def test_move(client):
    client.post('/api/bins', json=bin1.to_json())
    client.post('/api/bins', json=bin2.to_json())
    client.post('/api/skus', json=sku1.to_json())
    client.post('/api/receive', json={
        "bin_id": bin1.id,
        "sku_id": sku1.id,
        "quantity": 2
    })
