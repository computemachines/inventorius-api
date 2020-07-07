from flask import Blueprint, request
from inventory.data_models import Batch, DataModelJSONEncoder as Encoder
from inventory.db import db

import json

batch = Blueprint("batch", __name__)
