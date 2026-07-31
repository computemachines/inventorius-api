"""Read-only verification of the ``inventory_holdings`` projection.

This intentionally accepts documents supplied by a caller.  Loading the two
Mongo collections belongs in a later slice: the application's normal database
accessor creates indexes and is therefore not a suitable read-only audit seam.
"""

from __future__ import annotations

from decimal import Decimal, Inexact, InvalidOperation, Overflow, Rounded, localcontext
import hashlib
import json
from typing import Any, Iterable, Mapping

from bson.decimal128 import create_decimal128_context


PROJECTION_NAME = "inventory_holdings"
PROJECTION_VERSION = 1
_KINDS = frozenset({"receive", "transfer", "release", "correction", "reconciliation"})
_IDENTITY_FIELDS = (
    "batch_id", "location_id", "unit", "packaging_configuration_id",
)


class ProjectionDecodeError(ValueError):
    """A stored fact cannot safely participate in a projection comparison."""

    def __init__(self, operation_id: object, reason: str):
        self.operation_id = str(operation_id) if operation_id is not None else "<missing>"
        self.reason = reason
        super().__init__(f"operation {self.operation_id}: {reason}")


def _decimal(value: object, *, operation_id: object, allow_zero: bool) -> Decimal:
    # bson.Decimal128 exposes ``to_decimal``.  Decimal and integer/string forms
    # make this module useful for projected fixtures without weakening checks.
    if hasattr(value, "to_decimal"):
        value = value.to_decimal()
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ProjectionDecodeError(operation_id, "unsupported quantity")
    try:
        with localcontext(create_decimal128_context()) as context:
            amount = context.create_decimal(value if isinstance(value, str) else str(value))
    except (InvalidOperation, ValueError):
        raise ProjectionDecodeError(operation_id, "invalid quantity") from None
    if context.flags[Overflow]:
        raise ProjectionDecodeError(operation_id, "quantity overflows Decimal128")
    if not amount.is_finite():
        raise ProjectionDecodeError(operation_id, "non-finite quantity")
    if context.flags[Inexact] or context.flags[Rounded]:
        raise ProjectionDecodeError(operation_id, "quantity is not Decimal128-exact")
    if not allow_zero and amount == 0:
        raise ProjectionDecodeError(operation_id, "zero quantity")
    return amount


def _add_decimal128(
    left: Decimal, right: Decimal, *, operation_id: object,
) -> Decimal:
    """Add exactly under Mongo Decimal128 semantics or fail closed."""
    with localcontext(create_decimal128_context()) as context:
        result = context.add(left, right)
    if context.flags[Overflow]:
        raise ProjectionDecodeError(operation_id, "quantity sum overflows Decimal128")
    if context.flags[Inexact] or context.flags[Rounded]:
        raise ProjectionDecodeError(operation_id, "quantity sum is not Decimal128-exact")
    if not result.is_finite():
        raise ProjectionDecodeError(operation_id, "non-finite quantity sum")
    return result


def _identity(raw: Mapping[str, Any], *, operation_id: object) -> tuple[str, str, str, str | None]:
    if not isinstance(raw, Mapping):
        raise ProjectionDecodeError(operation_id, "malformed holding leg")
    batch_id, location_id, unit = (raw.get(field) for field in _IDENTITY_FIELDS[:3])
    packaging = raw.get("packaging_configuration_id")
    if not all(isinstance(value, str) and value for value in (batch_id, location_id, unit)):
        raise ProjectionDecodeError(operation_id, "malformed holding identity")
    if packaging is not None and (not isinstance(packaging, str) or not packaging):
        raise ProjectionDecodeError(operation_id, "malformed packaging configuration identity")
    return batch_id, location_id, unit, packaging


def _format_decimal(value: Decimal) -> str:
    """Return one exact spelling without context-sensitive normalization.

    ``Decimal.normalize`` performs arithmetic in the ambient context.  Tuple
    canonicalization instead preserves every supported exponent and avoids
    turning a valid Decimal128 edge value into infinity during digesting.
    """
    if not value.is_finite():
        raise ValueError("only finite Decimal128 values can be formatted")
    if value == 0:
        return "0"
    sign, raw_digits, exponent = value.as_tuple()
    digits = list(raw_digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    prefix = "-" if sign else ""
    point = len(coefficient) + exponent
    if exponent >= 0 and point <= 64:
        return prefix + coefficient + ("0" * exponent)
    if exponent < 0 and point > 0:
        return prefix + coefficient[:point] + "." + coefficient[point:]
    if exponent < 0 and point >= -6:
        return prefix + "0." + ("0" * -point) + coefficient
    adjusted = point - 1
    fraction = ("." + coefficient[1:]) if len(coefficient) > 1 else ""
    return f"{prefix}{coefficient[0]}{fraction}E{adjusted:+d}"


def _row(identity: tuple[str, str, str, str | None], quantity: Decimal) -> dict[str, object]:
    return dict(zip(_IDENTITY_FIELDS, identity), quantity=_format_decimal(quantity))


def _identity_sort_key(identity: tuple[str, str, str, str | None]) -> tuple[str, str, str, str]:
    return identity[0], identity[1], identity[2], identity[3] or ""


def _fact_schema(raw: Mapping[str, Any], operation_id: object) -> bool:
    """Return whether this is an enveloped, hence provenance-verifiable, fact."""
    if "fact_schema" not in raw:
        return False  # actor-less historical facts predate the fact envelope.
    schema = raw["fact_schema"]
    if not isinstance(schema, Mapping):
        raise ProjectionDecodeError(operation_id, "malformed explicit fact_schema")
    if schema.get("name") != "inventory.operation" or schema.get("version") != 1:
        raise ProjectionDecodeError(operation_id, "unknown explicit fact_schema version")
    if raw.get("fact_type", "inventory.operation") != "inventory.operation":
        raise ProjectionDecodeError(operation_id, "unknown explicit fact type")
    if raw.get("envelope_version", 1) != 1:
        raise ProjectionDecodeError(operation_id, "unknown explicit envelope version")
    return True


def _decode_operation(raw: Mapping[str, Any]) -> tuple[str, str, tuple[tuple[tuple[str, str, str, str | None], Decimal], ...], bool]:
    if not isinstance(raw, Mapping):
        raise ProjectionDecodeError(None, "malformed operation document")
    operation_id = raw.get("_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise ProjectionDecodeError(operation_id, "missing operation ID")
    verifiable = _fact_schema(raw, operation_id)
    kind = raw.get("kind")
    if kind not in _KINDS:
        raise ProjectionDecodeError(operation_id, "unknown operation kind")
    legs = raw.get("legs")
    if not isinstance(legs, list) or not legs:
        raise ProjectionDecodeError(operation_id, "malformed legs")
    decoded = []
    identities = set()
    for leg in legs:
        identity = _identity(leg, operation_id=operation_id)
        if identity in identities:
            raise ProjectionDecodeError(operation_id, "duplicate holding identity in legs")
        identities.add(identity)
        decoded.append((identity, _decimal(leg.get("quantity"), operation_id=operation_id, allow_zero=False)))
    quantities = [amount for _, amount in decoded]
    if kind == "receive" and any(amount < 0 for amount in quantities):
        raise ProjectionDecodeError(operation_id, "receive has a debit leg")
    if kind == "release" and any(amount > 0 for amount in quantities):
        raise ProjectionDecodeError(operation_id, "release has a credit leg")
    if kind == "transfer":
        if len(decoded) < 2 or not any(amount < 0 for amount in quantities) or not any(amount > 0 for amount in quantities):
            raise ProjectionDecodeError(operation_id, "malformed transfer legs")
        totals: dict[tuple[str, str, str | None], Decimal] = {}
        for (batch_id, _, unit, package_id), amount in sorted(
            decoded, key=lambda leg: _identity_sort_key(leg[0])
        ):
            transfer_identity = (batch_id, unit, package_id)
            if transfer_identity not in totals:
                totals[transfer_identity] = amount
            else:
                totals[transfer_identity] = _add_decimal128(
                    totals[transfer_identity], amount, operation_id=operation_id,
                )
        if any(total != 0 for total in totals.values()):
            raise ProjectionDecodeError(operation_id, "transfer does not preserve batch/package unit")
    if kind == "correction" and (not isinstance(raw.get("corrects_operation_id"), str) or not raw["corrects_operation_id"] or raw["corrects_operation_id"] == operation_id):
        raise ProjectionDecodeError(operation_id, "malformed correction reference")
    if kind == "reconciliation" and (not isinstance(raw.get("reconciles_observation_id"), str) or not raw["reconciles_observation_id"]):
        raise ProjectionDecodeError(operation_id, "malformed reconciliation reference")
    return operation_id, kind, tuple(decoded), verifiable


def _source_digest(operations: list[tuple[str, str, tuple[tuple[tuple[str, str, str, str | None], Decimal], ...]]]) -> str:
    canonical = [
        {"operation_id": operation_id, "kind": kind, "legs": [_row(identity, amount) for identity, amount in sorted(legs, key=lambda leg: _identity_sort_key(leg[0]))]}
        for operation_id, kind, legs in sorted(operations)
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def compare_holdings_projection(
    operations: Iterable[Mapping[str, Any]], holdings: Iterable[Mapping[str, Any]],
) -> dict[str, object]:
    """Compare caller-supplied operation facts against Mongo projection rows.

    The result is deliberately fail-closed: if either input cannot be decoded,
    no consistency result or partial classifications are claimed.  There is no
    ``through_fact`` because these documents carry no canonical commit sequence.
    """
    malformed: list[dict[str, str]] = []
    unverifiable: list[dict[str, str]] = []
    decoded: list[tuple[str, str, tuple[tuple[tuple[str, str, str, str | None], Decimal], ...]]] = []
    operation_ids: set[str] = set()
    for raw in operations:
        try:
            operation_id, kind, legs, verifiable = _decode_operation(raw)
            if operation_id in operation_ids:
                raise ProjectionDecodeError(operation_id, "duplicate operation ID")
            operation_ids.add(operation_id)
            decoded.append((operation_id, kind, legs))
            if not verifiable:
                unverifiable.append({"operation_id": operation_id, "reason": "legacy actor-less fact envelope"})
        except ProjectionDecodeError as error:
            malformed.append({"operation_id": error.operation_id, "reason": error.reason})

    actual: dict[tuple[str, str, str, str | None], Decimal] = {}
    malformed_holdings: list[dict[str, str]] = []
    for raw in holdings:
        try:
            identity = _identity(raw, operation_id="<holding>")
            if identity in actual:
                raise ProjectionDecodeError("<holding>", "duplicate holding identity")
            amount = _decimal(raw.get("quantity"), operation_id="<holding>", allow_zero=True)
            if amount < 0:
                raise ProjectionDecodeError("<holding>", "negative holding quantity")
            actual[identity] = amount
        except ProjectionDecodeError as error:
            malformed_holdings.append({"holding_id": error.operation_id, "reason": error.reason})

    base = {
        "projection": {"name": PROJECTION_NAME, "version": PROJECTION_VERSION},
        "operation_count": len(decoded),
        "source_digest": _source_digest(decoded),
        "malformed_facts": sorted(malformed, key=lambda item: (item["operation_id"], item["reason"])),
        "unverifiable_facts": sorted(unverifiable, key=lambda item: item["operation_id"]),
        "malformed_holdings": sorted(malformed_holdings, key=lambda item: (item["holding_id"], item["reason"])),
    }
    if malformed or malformed_holdings:
        return base | {"is_consistent": False, "missing": [], "unexpected": [], "quantity_mismatches": []}

    expected: dict[tuple[str, str, str, str | None], Decimal] = {}
    reduction_failure = None
    for operation_id, _, legs in sorted(decoded, key=lambda item: item[0]):
        for identity, amount in sorted(legs, key=lambda leg: _identity_sort_key(leg[0])):
            try:
                if identity not in expected:
                    expected[identity] = amount
                else:
                    expected[identity] = _add_decimal128(
                        expected[identity], amount, operation_id=operation_id,
                    )
            except ProjectionDecodeError as error:
                reduction_failure = error
                break
        if reduction_failure is not None:
            break
    if reduction_failure is not None:
        base["malformed_facts"].append({
            "operation_id": reduction_failure.operation_id,
            "reason": reduction_failure.reason,
        })
        return base | {"is_consistent": False, "missing": [], "unexpected": [], "quantity_mismatches": []}
    negative = [identity for identity, amount in expected.items() if amount < 0]
    if negative:
        base["malformed_facts"].append({"operation_id": "<reduction>", "reason": f"negative final balance: {negative[0]}"})
        return base | {"is_consistent": False, "missing": [], "unexpected": [], "quantity_mismatches": []}

    missing = [_row(identity, expected[identity]) for identity in sorted(set(expected) - set(actual), key=_identity_sort_key)]
    unexpected = [_row(identity, actual[identity]) for identity in sorted(set(actual) - set(expected), key=_identity_sort_key)]
    mismatches = [
        _row(identity, expected[identity]) | {"actual_quantity": _format_decimal(actual[identity])}
        for identity in sorted(set(expected) & set(actual), key=_identity_sort_key) if expected[identity] != actual[identity]
    ]
    return base | {
        "is_consistent": not (missing or unexpected or mismatches),
        "missing": missing,
        "unexpected": unexpected,
        "quantity_mismatches": mismatches,
    }
