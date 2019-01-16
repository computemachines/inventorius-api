from flask import Flask
from flask import request, redirect
from flask.json import jsonify
import json
from bson.json_util import dumps

from urllib.parse import urlencode


app = Flask(__name__)


def if_numeric_then_prepend(string, prefix):
    if string.isnumeric():
        return prefix+string
    else:
        return string

@app.route('/api/things', methods=['POST', 'PUT'])
def things_post_put():
    if request.method == 'POST' and request.form['_method'].upper() == 'PUT':
        return things_put()
    elif request.method == 'PUT':
        return things_put()

def things_put():
    form_data = request.form.to_dict()

    thing_label = form_data['thing_label'].upper()
    bin_label = form_data['bin_label'].upper()

    thing_label = if_numeric_then_prepend(thing_label, 'UNIQ')
    bin_label = if_numeric_then_prepend(bin_label, 'BIN')

    db_entry = {
        'label': thing_label,
        'bin': bin_label,
        'name': form_data['thing_name']
    }
    
    db.things.insert_one(db_entry)

    ret = db.things.find_one({'label': thing_label})

    # refresh the page with note
    ret = redirect('/new/thing?' + urlencode({
        'last_inserted': thing_label
    }))
    print(ret)
    return ret

@app.route('/api/things', methods=['GET'])
def things_get():
    all_things = db.things.find()
    return dumps(all_things), 200

@app.route('/api/thing/<label>', methods=['GET'])
def thing(label):
    label = label.upper()
    label = if_numeric_then_prepend(label, 'UNIQ')
    
    thing = db.things.find_one({'label': label})
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
    app.run(port=8081, debug=True)
