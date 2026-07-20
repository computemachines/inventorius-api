"""Per-process MongoDB isolation for the API test suite.

Parallel Codex workers may run pytest at the same time.  A fixed ``testing``
database lets one process erase another process's fixtures, especially while a
Mongo transaction is being retried.  Giving each pytest process its own
database keeps those runs independent without changing production database
selection.
"""

from __future__ import annotations

import os

from inventorius.db import get_mongo_client


TEST_DATABASE_NAME = os.getenv(
    "INVENTORIUS_TEST_DATABASE",
    f"inventorius_testing_{os.getpid()}",
)


def get_test_database():
    return get_mongo_client()[TEST_DATABASE_NAME]
