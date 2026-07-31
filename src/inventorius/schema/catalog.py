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
from .repository import BOOTSTRAP_ACTOR, SchemaEditConflict, SchemaRepository


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
    actor: dict[str, str] | None = BOOTSTRAP_ACTOR,
) -> SchemaInstallResult:
    """Install missing schemas and publish forced catalog changes.

    A normal bootstrap preserves every existing logical schema.  A forced
    bootstrap still uses the immutable publication path: changed catalog
    content becomes a new revision rather than replacing either the head or its
    history.
    """
    installed: list[str] = []
    skipped: list[str] = []
    repository = SchemaRepository(collection.database)

    for name, factory in factories.items():
        definition = schema_to_dict(factory())
        observed = repository.head(name)
        if observed.exists and not force:
            skipped.append(name)
            continue

        try:
            publication = repository.publish(
                name,
                definition,
                actor=actor,
                expected=observed,
            )
        except SchemaEditConflict:
            # Bootstrap is intentionally conservative when another writer wins
            # the compare-and-swap race.  A later explicit invocation can
            # evaluate the newly current head.
            skipped.append(name)
            continue

        if publication.changed:
            installed.append(name)
        else:
            skipped.append(name)

    return SchemaInstallResult(installed=installed, skipped=skipped)
