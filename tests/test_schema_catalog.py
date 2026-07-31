"""Tests for publishing built-in schemas without clobbering edits."""

import pytest

from inventorius.schema.catalog import DEFAULT_SCHEMA_FACTORIES, install_schemas
from inventorius.schema.sample_schemas import get_sku_schema
from tests.database import get_test_database


@pytest.fixture(autouse=True)
def clean_schema_catalog_database():
    database = get_test_database()
    database.schema.delete_many({})
    database.schema_revision.delete_many({})
    yield database


def test_default_catalog_contains_only_application_schemas():
    assert list(DEFAULT_SCHEMA_FACTORIES) == ["sku", "batch"]


def test_install_schemas_reports_installed_and_preserved_documents(
    clean_schema_catalog_database,
):
    collection = clean_schema_catalog_database.schema

    first = install_schemas(collection)
    second = install_schemas(collection)

    assert first.installed == ["sku", "batch"]
    assert first.skipped == []
    assert second.installed == []
    assert second.skipped == ["sku", "batch"]
    head = collection.find_one({"_id": "sku"})
    assert head["head_revision"] == 1
    assert head["active_revision"] == 1
    assert head["definition"]["root_mixins"] == ["ItemTypeSelector"]


def test_force_install_publishes_changed_content_instead_of_replacing_history(
    clean_schema_catalog_database,
):
    collection = clean_schema_catalog_database.schema
    assert install_schemas(collection, {"sku": get_sku_schema}).installed == [
        "sku"
    ]

    def changed_sku_schema():
        schema = get_sku_schema()
        schema.root_mixins = []
        return schema

    result = install_schemas(
        collection,
        {"sku": changed_sku_schema},
        force=True,
    )

    assert result.installed == ["sku"]
    assert result.skipped == []
    head = collection.find_one({"_id": "sku"})
    assert head["head_revision"] == 2
    assert head["definition"]["root_mixins"] == []
    revisions = list(
        clean_schema_catalog_database.schema_revision.find(
            {"schema_name": "sku"}
        ).sort("revision")
    )
    assert [revision["revision"] for revision in revisions] == [1, 2]
    assert revisions[0]["definition"]["root_mixins"] == [
        "ItemTypeSelector"
    ]
    assert revisions[1]["parent_revision"] == 1


def test_force_install_identical_content_is_a_no_op(
    clean_schema_catalog_database,
):
    collection = clean_schema_catalog_database.schema
    install_schemas(collection, {"sku": get_sku_schema})

    result = install_schemas(
        collection,
        {"sku": get_sku_schema},
        force=True,
    )

    assert result.installed == []
    assert result.skipped == ["sku"]
    assert clean_schema_catalog_database.schema_revision.count_documents(
        {"schema_name": "sku"}
    ) == 1
