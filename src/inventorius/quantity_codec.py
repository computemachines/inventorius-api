"""Strict, lossless wire forms for quantity-native facts.

Only semantic holding identities, state references, claims, and effects cross
this boundary.  Solver variable names, witnesses, conflicts, and derived
intervals are deliberately absent: they are disposable query results.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
from math import gcd
from typing import Mapping

from inventorius.ledger import HoldingKey
from inventorius.quantity_constraints import (
    Number,
    ObservationBasis,
    QuantityDomain,
    QuantityObservation,
)


EFFECT_CODEC_NAME = "inventorius.quantity-effect"
OBSERVATION_CODEC_NAME = "inventorius.quantity-observation"
CODEC_VERSION = 1


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual == expected:
        return
    details = []
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        details.append(f"missing {missing}")
    if unexpected:
        details.append(f"unexpected {unexpected}")
    raise ValueError(f"{field} has invalid fields: {', '.join(details)}")


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def rational_document(value: Fraction) -> dict[str, str]:
    """Encode one already-reduced exact rational without Decimal128 loss."""

    if not isinstance(value, Fraction):
        raise ValueError("quantity must be a Fraction")
    return {
        "numerator": str(value.numerator),
        "denominator": str(value.denominator),
    }


def rational_from_document(value: object, field: str) -> Fraction:
    document = _mapping(value, field)
    _exact_keys(document, {"numerator", "denominator"}, field)
    numerator = document["numerator"]
    denominator = document["denominator"]
    if (
        not isinstance(numerator, str)
        or not isinstance(denominator, str)
        or not numerator
        or not denominator
    ):
        raise ValueError(f"{field} numerator and denominator must be strings")
    if numerator.startswith("+") or denominator.startswith(("+", "-")):
        raise ValueError(f"{field} must use canonical integer strings")
    try:
        numerator_int = int(numerator)
        denominator_int = int(denominator)
    except ValueError as error:
        raise ValueError(f"{field} must use canonical integer strings") from error
    if str(numerator_int) != numerator or str(denominator_int) != denominator:
        raise ValueError(f"{field} must use canonical integer strings")
    if denominator_int <= 0:
        raise ValueError(f"{field} denominator must be positive")
    if gcd(abs(numerator_int), denominator_int) != 1:
        raise ValueError(f"{field} must be reduced")
    return Fraction(numerator_int, denominator_int)


def holding_document(holding: HoldingKey) -> dict[str, str | None]:
    if not isinstance(holding, HoldingKey):
        raise ValueError("holding must be a HoldingKey")
    return {
        "batch_id": holding.batch_id,
        "location_id": holding.location_id,
        "unit": holding.unit,
        "packaging_configuration_id": holding.packaging_configuration_id,
    }


def holding_from_document(value: object, field: str = "holding") -> HoldingKey:
    document = _mapping(value, field)
    _exact_keys(
        document,
        {
            "batch_id",
            "location_id",
            "unit",
            "packaging_configuration_id",
        },
        field,
    )
    package = document["packaging_configuration_id"]
    if package is not None:
        package = _nonblank(package, f"{field}.packaging_configuration_id")
    return HoldingKey(
        _nonblank(document["batch_id"], f"{field}.batch_id"),
        _nonblank(document["location_id"], f"{field}.location_id"),
        _nonblank(document["unit"], f"{field}.unit"),
        package,
    )


def quantity_stream_id(holding: HoldingKey) -> str:
    encoded = json.dumps(
        holding_document(holding),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "QSH" + sha256(encoded).hexdigest()[:32]


def output_state_id(operation_id: str, holding: HoldingKey) -> str:
    stable_operation_id = _nonblank(operation_id, "operation_id")
    encoded = json.dumps(
        {
            "operation_id": stable_operation_id,
            "holding": holding_document(holding),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "QST" + sha256(encoded).hexdigest()[:32]


@dataclass(frozen=True)
class QuantityClaim:
    """One source claim, including a separately retained hard capacity."""

    basis: ObservationBasis
    lower: Fraction | None = None
    preferred: Fraction | None = None
    upper: Fraction | None = None
    capacity: Fraction | None = None

    def __init__(
        self,
        *,
        basis: ObservationBasis,
        lower: Number | None = None,
        preferred: Number | None = None,
        upper: Number | None = None,
        capacity: Number | None = None,
    ):
        if not isinstance(basis, ObservationBasis):
            raise ValueError("basis must be an ObservationBasis")
        normalized = QuantityObservation(
            "claim-validation",
            lower=lower,
            preferred=preferred,
            upper=upper,
            basis=basis,
        )
        if capacity is None:
            normalized_capacity = None
        else:
            if isinstance(capacity, bool) or not isinstance(
                capacity, (Fraction, int, str)
            ):
                raise ValueError(
                    "capacity must be an int, exact numeric string, or Fraction"
                )
            try:
                normalized_capacity = Fraction(capacity)
            except (ValueError, ZeroDivisionError) as error:
                raise ValueError("capacity must be an exact number") from error
        if normalized_capacity is not None and normalized_capacity < 0:
            raise ValueError("capacity must be nonnegative")
        if (
            normalized_capacity is not None
            and normalized.upper is not None
            and normalized.upper > normalized_capacity
        ):
            raise ValueError("upper quantity exceeds capacity")
        if basis == ObservationBasis.COUNTED:
            counted_values = (
                normalized.lower,
                normalized.preferred,
                normalized.upper,
            )
            if (
                any(value is None for value in counted_values)
                or len(set(counted_values)) != 1
            ):
                raise ValueError(
                    "a counted claim must use one exact lower, preferred, and upper value"
                )
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "lower", normalized.lower)
        object.__setattr__(self, "preferred", normalized.preferred)
        object.__setattr__(self, "upper", normalized.upper)
        object.__setattr__(self, "capacity", normalized_capacity)

    @classmethod
    def estimated(
        cls,
        preferred: Number,
        *,
        lower: Number = 0,
        upper: Number | None = None,
        capacity: Number | None = None,
    ) -> "QuantityClaim":
        estimate = QuantityObservation.estimated(
            "claim-defaults",
            preferred,
            lower=lower,
            upper=upper,
        )
        return cls(
            basis=estimate.basis,
            lower=estimate.lower,
            preferred=estimate.preferred,
            upper=estimate.upper,
            capacity=capacity,
        )

    def as_observation(self, fact_id: str) -> QuantityObservation:
        effective_upper = self.upper
        if effective_upper is None:
            effective_upper = self.capacity
        elif self.capacity is not None:
            effective_upper = min(effective_upper, self.capacity)
        return QuantityObservation(
            fact_id,
            lower=self.lower,
            preferred=self.preferred,
            upper=effective_upper,
            basis=self.basis,
        )


def claim_document(claim: QuantityClaim) -> dict[str, object]:
    if not isinstance(claim, QuantityClaim):
        raise ValueError("claim must be a QuantityClaim")
    return {
        "basis": claim.basis.value,
        "lower": None if claim.lower is None else rational_document(claim.lower),
        "preferred": (
            None
            if claim.preferred is None
            else rational_document(claim.preferred)
        ),
        "upper": None if claim.upper is None else rational_document(claim.upper),
        "capacity": (
            None
            if claim.capacity is None
            else rational_document(claim.capacity)
        ),
    }


def claim_from_document(value: object, field: str = "claim") -> QuantityClaim:
    document = _mapping(value, field)
    _exact_keys(
        document,
        {"basis", "lower", "preferred", "upper", "capacity"},
        field,
    )
    try:
        basis = ObservationBasis(document["basis"])
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field}.basis is not supported") from error

    def optional_rational(name: str) -> Fraction | None:
        item = document[name]
        return None if item is None else rational_from_document(item, f"{field}.{name}")

    return QuantityClaim(
        basis=basis,
        lower=optional_rational("lower"),
        preferred=optional_rational("preferred"),
        upper=optional_rational("upper"),
        capacity=optional_rational("capacity"),
    )


def claim_from_input(value: Mapping[str, object]) -> QuantityClaim:
    """Normalize an already schema-shaped HTTP claim into exact values."""

    try:
        basis = ObservationBasis(value["basis"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("basis is not supported") from error
    preferred = value.get("preferred")
    if basis == ObservationBasis.ESTIMATED and preferred is not None:
        return QuantityClaim.estimated(
            preferred,
            lower=value.get("lower", 0),
            upper=value.get("upper"),
            capacity=value.get("capacity"),
        )
    return QuantityClaim(
        basis=basis,
        lower=value.get("lower"),
        preferred=preferred,
        upper=value.get("upper"),
        capacity=value.get("capacity"),
    )


def _codec(document: Mapping[str, object], expected_name: str, field: str) -> None:
    codec = _mapping(document.get("codec"), f"{field}.codec")
    _exact_keys(codec, {"name", "version"}, f"{field}.codec")
    if codec["name"] != expected_name or codec["version"] != CODEC_VERSION:
        raise ValueError(f"unsupported {field} codec")


@dataclass(frozen=True)
class OpeningEffect:
    stream_id: str
    sequence: int
    holding: HoldingKey
    domain: QuantityDomain
    output_state_id: str
    claim: QuantityClaim


@dataclass(frozen=True)
class WithdrawalEffect:
    stream_id: str
    sequence: int
    holding: HoldingKey
    domain: QuantityDomain
    predecessor_state_id: str
    output_state_id: str
    amount: Fraction


def opening_effect_document(
    *,
    sequence: int,
    holding: HoldingKey,
    domain: QuantityDomain,
    output_state: str,
    claim: QuantityClaim,
) -> dict[str, object]:
    return {
        "codec": {"name": EFFECT_CODEC_NAME, "version": CODEC_VERSION},
        "kind": "opening",
        "stream_id": quantity_stream_id(holding),
        "sequence": _nonnegative_integer(sequence, "sequence"),
        "holding": holding_document(holding),
        "domain": domain.value,
        "predecessor_state_id": None,
        "output_state_id": _nonblank(output_state, "output_state_id"),
        "claim": claim_document(claim),
        "amount": None,
    }


def withdrawal_effect_document(
    *,
    sequence: int,
    holding: HoldingKey,
    domain: QuantityDomain,
    predecessor_state: str,
    output_state: str,
    amount: Fraction,
) -> dict[str, object]:
    if not isinstance(amount, Fraction) or amount <= 0:
        raise ValueError("withdrawal amount must be a positive Fraction")
    return {
        "codec": {"name": EFFECT_CODEC_NAME, "version": CODEC_VERSION},
        "kind": "withdrawal",
        "stream_id": quantity_stream_id(holding),
        "sequence": _nonnegative_integer(sequence, "sequence"),
        "holding": holding_document(holding),
        "domain": domain.value,
        "predecessor_state_id": _nonblank(
            predecessor_state, "predecessor_state_id"
        ),
        "output_state_id": _nonblank(output_state, "output_state_id"),
        "claim": None,
        "amount": rational_document(amount),
    }


def effect_from_document(value: object) -> OpeningEffect | WithdrawalEffect:
    document = _mapping(value, "quantity_effect")
    _exact_keys(
        document,
        {
            "codec",
            "kind",
            "stream_id",
            "sequence",
            "holding",
            "domain",
            "predecessor_state_id",
            "output_state_id",
            "claim",
            "amount",
        },
        "quantity_effect",
    )
    _codec(document, EFFECT_CODEC_NAME, "quantity_effect")
    holding = holding_from_document(document["holding"])
    stream_id = _nonblank(document["stream_id"], "quantity_effect.stream_id")
    if stream_id != quantity_stream_id(holding):
        raise ValueError("quantity_effect stream identity does not match holding")
    sequence = _nonnegative_integer(
        document["sequence"], "quantity_effect.sequence"
    )
    try:
        domain = QuantityDomain(document["domain"])
    except (TypeError, ValueError) as error:
        raise ValueError("quantity_effect.domain is not supported") from error
    output_state = _nonblank(
        document["output_state_id"], "quantity_effect.output_state_id"
    )
    if document["kind"] == "opening":
        if document["predecessor_state_id"] is not None or document["amount"] is not None:
            raise ValueError("opening effect cannot have predecessor or amount")
        return OpeningEffect(
            stream_id,
            sequence,
            holding,
            domain,
            output_state,
            claim_from_document(document["claim"], "quantity_effect.claim"),
        )
    if document["kind"] == "withdrawal":
        if document["claim"] is not None:
            raise ValueError("withdrawal effect cannot have a claim")
        predecessor = _nonblank(
            document["predecessor_state_id"],
            "quantity_effect.predecessor_state_id",
        )
        amount = rational_from_document(
            document["amount"], "quantity_effect.amount"
        )
        if amount <= 0:
            raise ValueError("withdrawal amount must be positive")
        return WithdrawalEffect(
            stream_id,
            sequence,
            holding,
            domain,
            predecessor,
            output_state,
            amount,
        )
    raise ValueError("quantity_effect.kind is not supported")


@dataclass(frozen=True)
class QuantityEvidence:
    stream_id: str
    sequence: int
    holding: HoldingKey
    domain: QuantityDomain
    state_id: str
    claim: QuantityClaim
    supersedes_fact_id: str | None


def observation_document(
    *,
    sequence: int,
    holding: HoldingKey,
    domain: QuantityDomain,
    state_id: str,
    claim: QuantityClaim,
    supersedes_fact_id: str | None = None,
) -> dict[str, object]:
    return {
        "codec": {"name": OBSERVATION_CODEC_NAME, "version": CODEC_VERSION},
        "stream_id": quantity_stream_id(holding),
        "sequence": _nonnegative_integer(sequence, "sequence"),
        "holding": holding_document(holding),
        "domain": domain.value,
        "state_id": _nonblank(state_id, "state_id"),
        "claim": claim_document(claim),
        "supersedes_fact_id": (
            None
            if supersedes_fact_id is None
            else _nonblank(supersedes_fact_id, "supersedes_fact_id")
        ),
    }


def observation_from_document(value: object) -> QuantityEvidence:
    document = _mapping(value, "quantity_observation")
    _exact_keys(
        document,
        {
            "codec",
            "stream_id",
            "sequence",
            "holding",
            "domain",
            "state_id",
            "claim",
            "supersedes_fact_id",
        },
        "quantity_observation",
    )
    _codec(document, OBSERVATION_CODEC_NAME, "quantity_observation")
    holding = holding_from_document(document["holding"])
    stream_id = _nonblank(
        document["stream_id"], "quantity_observation.stream_id"
    )
    if stream_id != quantity_stream_id(holding):
        raise ValueError("quantity_observation stream identity does not match holding")
    try:
        domain = QuantityDomain(document["domain"])
    except (TypeError, ValueError) as error:
        raise ValueError("quantity_observation.domain is not supported") from error
    supersedes = document["supersedes_fact_id"]
    if supersedes is not None:
        supersedes = _nonblank(
            supersedes, "quantity_observation.supersedes_fact_id"
        )
    return QuantityEvidence(
        stream_id,
        _nonnegative_integer(
            document["sequence"], "quantity_observation.sequence"
        ),
        holding,
        domain,
        _nonblank(document["state_id"], "quantity_observation.state_id"),
        claim_from_document(document["claim"], "quantity_observation.claim"),
        supersedes,
    )
