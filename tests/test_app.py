import os
import sys
import tempfile

import pytest

print(sys.path)

import inventory.app
inventory_flask_app  = inventory.app.app

@pytest.fixture
def client():
    app = inventory_flask_app
    yield app
    #close app

def test_empty_db(client):
    assert False
    
