"""Tests for installing built-in schemas without clobbering edits."""

from types import SimpleNamespace
from unittest.mock import Mock

from inventorius.schema.catalog import DEFAULT_SCHEMA_FACTORIES, install_schemas


def test_default_catalog_contains_only_application_schemas():
    assert list(DEFAULT_SCHEMA_FACTORIES) == ["sku", "batch"]


def test_install_schemas_reports_installed_and_preserved_documents():
    collection = Mock()
    collection.update_one.side_effect = [
        SimpleNamespace(upserted_id="sku"),
        SimpleNamespace(upserted_id=None),
    ]

    result = install_schemas(collection)

    assert result.installed == ["sku"]
    assert result.skipped == ["batch"]
    first_document = collection.update_one.call_args_list[0].args[1]["$setOnInsert"]
    assert first_document["_id"] == "sku"
    assert first_document["root_mixins"] == ["ItemTypeSelector"]


def test_force_install_replaces_existing_documents():
    collection = Mock()

    result = install_schemas(collection, force=True)

    assert result.installed == ["sku", "batch"]
    assert result.skipped == []
    assert collection.replace_one.call_count == 2
    collection.update_one.assert_not_called()
