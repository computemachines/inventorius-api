"""Built-in schema catalog and installation helpers.

The SKU and Batch schemas are application defaults.  The deeper electronics and
decimal schemas are useful demonstrations, but should not silently appear in a
normal installation.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .sample_schemas import (
    get_batch_schema,
    get_decimal_schema,
    get_electronics_schema,
    get_sku_schema,
)
from .trigger_engine import Schema, schema_to_dict


SchemaFactory = Callable[[], Schema]

DEFAULT_SCHEMA_FACTORIES: Mapping[str, SchemaFactory] = {
    "sku": get_sku_schema,
    "batch": get_batch_schema,
}

EXAMPLE_SCHEMA_FACTORIES: Mapping[str, SchemaFactory] = {
    "electronics": get_electronics_schema,
    "decimal": get_decimal_schema,
}


@dataclass(frozen=True)
class SchemaInstallResult:
    installed: list[str]
    skipped: list[str]


def install_schemas(
    collection: Any,
    factories: Mapping[str, SchemaFactory] = DEFAULT_SCHEMA_FACTORIES,
    *,
    force: bool = False,
) -> SchemaInstallResult:
    """Install schemas without replacing administrator changes by default."""
    installed: list[str] = []
    skipped: list[str] = []

    for name, factory in factories.items():
        document = schema_to_dict(factory())
        document["_id"] = name

        if force:
            collection.replace_one({"_id": name}, document, upsert=True)
            installed.append(name)
            continue

        result = collection.update_one(
            {"_id": name},
            {"$setOnInsert": document},
            upsert=True,
        )
        if result.upserted_id is None:
            skipped.append(name)
        else:
            installed.append(name)

    return SchemaInstallResult(installed=installed, skipped=skipped)
