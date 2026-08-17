"""Configuration shared only by the persistence-free solver laboratory."""

import sys
from pathlib import Path

# The ``pytest`` console entry point does not reliably put the repository root
# on ``sys.path`` when this directory is collected alone.  Keep test-oracle
# imports stable without importing the repository-level Mongo conftest.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def pytest_configure(config):
    """Declare the laboratory marker without loading the root Mongo fixtures."""

    config.addinivalue_line(
        "markers",
        "solver_laboratory: persistence-free constraint-solver experiment",
    )


def pytest_collection_modifyitems(items):
    """Label laboratory tests so they remain easy to select independently."""

    for item in items:
        if "/tests/solver/" in str(item.path):
            item.add_marker("solver_laboratory")
