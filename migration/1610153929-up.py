import sys
sys.path.append('..')

from inventory import db
client = db.get_mongo_client()
db = client.get_database("inventorydb")

for bin in db.bin.find({}):
    db.bin.update_one({"_id": bin["_id"]},
                      {"$set": {"contents": {
                          content['id']: content['quantity'] for content in bin["contents"]
                      }}})

list(db.search.find({}))
for sku in db.sku.find({}):
    db.sku.insert_one({
        "_id": sku['id'],
        "name": sku["name"],
        "owned_codes": sku["owned_codes"]
    })
    db.sku.delete_one({"_id": sku["_id"]})

for uniq in db.uniq.find({}):
    db.batch.insert_one({
        "_id": uniq['id'],
        "name": uniq['name'],
        "owned_codes": uniq['owned_codes']
    })
db.uniq.drop()
db.search.drop()


def drop_all():
    for name in client.database_names():
        if name != "admin":
            client.drop_database(name)
