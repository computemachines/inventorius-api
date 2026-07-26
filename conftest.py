import contextlib
import hashlib
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import settings

from flask import g, request_started

# Ensure the application package on the src/ path is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
# The local Mongo replica set advertises its Compose hostname (``mongo``),
# which a host pytest process cannot resolve.  Direct connection keeps local
# tests on the published port; CI or another caller can still supply its own
# explicit URI.
os.environ.setdefault(
    "INVENTORIUS_MONGO_URI",
    "mongodb://localhost:27017/?replicaSet=inventorius-rs&directConnection=true",
)
from inventorius import app as inventorius_flask_app
from inventorius.db import get_mongo_client
from tests.database import get_test_database


# These integration/property tests exercise a real MongoDB database. Their
# correctness is not time-dependent, and machine or disk load makes per-example
# deadlines inherently flaky.
settings.register_profile("ci", deadline=None)
settings.load_profile("ci")

# from contextlib import contextmanager


def subscriber(sender):
    g.db = get_test_database()


request_started.connect(subscriber, inventorius_flask_app)

TEST_AUTH_ORIGIN = "http://localhost:3000"


def _authenticated_test_client():
    """Build a real server-side owner session for mutation tests."""

    inventorius_flask_app.config.update(
        AUTH_ORIGIN=TEST_AUTH_ORIGIN,
        AUTH_RP_ID="localhost",
        AUTH_RP_NAME="Inventorius Tests",
        AUTH_OWNER_DISPLAY_NAME="Test Owner",
        AUTH_COOKIE_SECURE=False,
    )
    database = get_test_database()
    database.auth_principals.replace_one(
        {"_id": "owner"},
        {
            "_id": "owner",
            "display_name": "Test Owner",
            "kind": "owner",
            "user_handle": b"test-owner",
            "created_at": datetime.now(timezone.utc),
        },
        upsert=True,
    )
    raw_session = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    database.auth_sessions.insert_one(
        {
            "_id": hashlib.sha256(raw_session.encode("ascii")).hexdigest(),
            "principal_id": "owner",
            "csrf_token": csrf_token,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    )
    test_client = inventorius_flask_app.test_client()
    test_client.set_cookie("inventorius_session", raw_session)
    test_client.environ_base["HTTP_ORIGIN"] = TEST_AUTH_ORIGIN
    test_client.environ_base["HTTP_X_CSRF_TOKEN"] = csrf_token
    return test_client


@pytest.fixture
def client():
    inventorius_flask_app.testing = True
    database = get_test_database()
    database.auth_sessions.delete_many({})
    yield _authenticated_test_client()
    database.auth_sessions.delete_many({})


@pytest.fixture
def anonymous_client():
    """A public caller with an Origin but no owner session."""

    inventorius_flask_app.testing = True
    inventorius_flask_app.config.update(
        AUTH_ORIGIN=TEST_AUTH_ORIGIN,
        AUTH_RP_ID="localhost",
        AUTH_RP_NAME="Inventorius Tests",
        AUTH_OWNER_DISPLAY_NAME="Test Owner",
        AUTH_COOKIE_SECURE=False,
    )
    test_client = inventorius_flask_app.test_client()
    test_client.environ_base["HTTP_ORIGIN"] = TEST_AUTH_ORIGIN
    return test_client


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database():
    """Start clean and remove this pytest process's private database."""
    database = get_test_database()
    get_mongo_client().drop_database(database.name)
    yield
    get_mongo_client().drop_database(database.name)


@contextlib.contextmanager
def clientContext():
    inventorius_flask_app.testing = True
    test_db = get_test_database()
    test_db.admin.delete_many({})
    test_db.batch.delete_many({})
    test_db.bin.delete_many({})
    test_db.inventory_code_observations.delete_many({})
    test_db.inventory_counters.delete_many({})
    test_db.inventory_holdings.delete_many({})
    test_db.inventory_operations.delete_many({})
    test_db.identifier_counters.delete_many({})
    test_db.resource_commands.delete_many({})
    test_db.resource_identifiers.delete_many({})
    test_db.sku.delete_many({})
    test_db.user.delete_many({})
    for collection_name in (
        "auth_bootstrap_tokens",
        "auth_challenges",
        "auth_credentials",
        "auth_principals",
        "auth_recovery_codes",
        "auth_sessions",
    ):
        test_db[collection_name].delete_many({})
    yield _authenticated_test_client()
