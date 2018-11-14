from flask import Flask
from flask import request
from flask.json import jsonify
import json
from bson.json_util import dumps


app = Flask(__name__)


@app.route('/api/things', methods=['POST'])
def things_post():
    print(request)
    print(request.form.to_dict())
    data = request.form.to_dict()
    label = data["label"]
    db.things.insert_one(data)
    ret = db.things.find_one({"label": label})
    return dumps(ret), 201

@app.route('/api/things', methods=['GET'])
def things_get():
    all_things = db.things.find()
    return dumps(all_things), 200

@app.route('/api/thing/<label>', methods=['GET'])
def thing(label):
    thing = db.things.find_one({"label": label})
    print(label)
    return dumps(thing), 200

@app.route('/api/bins', methods=['PUT'])
def bins_put():
    data = request.json
    db.bins.insert_one(data)
    return dumps(db.bins.find_one({'label': data['label']})), 201

@app.route('/api/bin/<label>', methods=['GET'])
def bin(label):
    ret = db.bins.find_one({"label": label})
    print(ret)
    return dumps(ret), 200


from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

DEBUG = __name__=='__main__'
if DEBUG:
    db_host = "localhost"
else:
    db_host = "mongo"
    import time
    time.sleep(5)
print(db_host)
client = MongoClient(db_host, 27017)
print("Connected to MongoDB")
db = client.inventorydb
print(db.bins.find_one())

if __name__=='__main__':
    app.run(port=8080, debug=True)
