from copy import deepcopy
from decimal import Decimal
import math

import pytest

from inventorius.holdings_projection import compare_holdings_projection
from inventorius.ledger import HoldingKey
from inventorius.quantity_codec import (
    QuantityClaim,
    opening_effect_document,
    output_state_id,
)
from inventorius.quantity_constraints import QuantityDomain


def leg(batch, location, quantity, *, unit="each", package=None):
    return {
        "batch_id": batch,
        "location_id": location,
        "unit": unit,
        "packaging_configuration_id": package,
        "quantity": quantity,
    }


def operation(operation_id, kind, legs, **extra):
    return {"_id": operation_id, "kind": kind, "legs": legs, **extra}


def all_kinds():
    return [
        operation("receive", "receive", [leg("batch", "one", "10")]),
        operation("transfer", "transfer", [leg("batch", "one", "-4"), leg("batch", "two", "4")]),
        operation("release", "release", [leg("batch", "two", "-1")]),
        operation("correction", "correction", [leg("batch", "two", "-1")], corrects_operation_id="receive"),
        operation("reconcile", "reconciliation", [leg("batch", "three", "3")], reconciles_observation_id="audit-1"),
    ]


def test_compares_all_five_kinds_with_full_identity_and_retained_zero_rows():
    operations = all_kinds()
    holdings = [
        leg("batch", "one", Decimal("6"), package=None) | {"_id": "ignored", "updated_at": "ignored"},
        leg("batch", "two", "2", package="case"),  # deliberately distinct package identity
        leg("batch", "two", "2"),
        leg("batch", "three", "3"),
        leg("zero", "empty", "0"),
    ]
    # The package row is an unexpected row; it proves package state participates
    # in identity while the zero row remains visible rather than being discarded.
    result = compare_holdings_projection(operations, holdings)

    assert result["operation_count"] == 5
    assert result["projection"] == {"name": "inventory_holdings", "version": 1}
    assert result["unexpected"] == [leg("batch", "two", "2", package="case"), leg("zero", "empty", "0")]
    assert result["missing"] == []
    assert result["quantity_mismatches"] == []


def test_actorless_legacy_and_version_one_fact_envelopes_are_accepted():
    operations = [
        operation("old", "receive", [leg("b", "l", 1)]),
        operation("new", "receive", [leg("b", "l2", 1)], fact_schema={"name": "inventory.operation", "version": 1}, fact_type="inventory.operation", envelope_version=1, actor={"principal_id": "p"}),
    ]
    result = compare_holdings_projection(operations, [leg("b", "l", 1), leg("b", "l2", 1)])

    assert result["is_consistent"] is True
    assert result["malformed_facts"] == []
    assert result["unverifiable_facts"] == [{"operation_id": "old", "reason": "legacy actor-less fact envelope"}]


def test_quantity_native_v2_fact_is_validated_but_excluded_from_exact_projection():
    holding = HoldingKey("BAT000001", "BIN000001", "each", None)
    operation_id = "quantity-opening"
    quantity_operation = operation(
        operation_id,
        "receive",
        [],
        fact_schema={"name": "inventory.operation", "version": 2},
        fact_type="inventory.operation",
        envelope_version=1,
        quantity_effect=opening_effect_document(
            sequence=0,
            holding=holding,
            domain=QuantityDomain.DISCRETE,
            output_state=output_state_id(operation_id, holding),
            claim=QuantityClaim.estimated(50),
        ),
    )

    result = compare_holdings_projection([quantity_operation], [])

    assert result["is_consistent"] is True
    assert result["operation_count"] == 0
    assert result["malformed_facts"] == []
    assert result["excluded_quantity_facts"] == [{
        "operation_id": operation_id,
        "reason": "quantity-native fact has no exact holding leg",
    }]


@pytest.mark.parametrize("mutator, reason", [
    (lambda doc: doc.update(kind="other"), "unknown operation kind"),
    (lambda doc: doc.update(fact_schema={"name": "inventory.operation", "version": 99}), "unknown explicit fact_schema version"),
    (lambda doc: doc.update(fact_schema={"name": "inventory.operation", "version": 2}), "quantity-native operation must not have exact legs"),
    (lambda doc: doc.update(legs=[{}]), "malformed holding identity"),
    (lambda doc: doc.update(legs=[leg("b", "l", 1), leg("b", "l", 2)]), "duplicate holding identity in legs"),
    (lambda doc: doc.update(legs=[leg("b", "l", 0)]), "zero quantity"),
    (lambda doc: doc.update(legs=[leg("b", "l", Decimal("NaN"))]), "non-finite quantity"),
    (lambda doc: doc.update(legs=[leg("b", "l", math.inf)]), "unsupported quantity"),
    (lambda doc: doc.update(legs=[leg("b", "l", Decimal("1." + "1" * 35))]), "quantity is not Decimal128-exact"),
])
def test_bad_facts_fail_closed_and_identify_the_operation(mutator, reason):
    document = operation("bad-op", "receive", [leg("b", "l", 1)])
    mutator(document)
    result = compare_holdings_projection([document], [])

    assert result["is_consistent"] is False
    assert result["malformed_facts"] == [{"operation_id": "bad-op", "reason": reason}]
    assert result["missing"] == result["unexpected"] == result["quantity_mismatches"] == []


def test_negative_final_balance_fails_closed_without_a_commit_order_claim():
    result = compare_holdings_projection([operation("release", "release", [leg("b", "l", -1)])], [])

    assert result["is_consistent"] is False
    assert result["malformed_facts"] == [{"operation_id": "<reduction>", "reason": "negative final balance: ('b', 'l', 'each', None)"}]
    assert "through_fact" not in result


def test_classifies_missing_unexpected_and_exact_quantity_mismatches():
    operations = [
        operation("one", "receive", [leg("b", "missing", 2), leg("b", "mismatch", 3), leg("b", "exact", 1)]),
    ]
    result = compare_holdings_projection(operations, [leg("b", "mismatch", 4), leg("b", "exact", 1), leg("b", "extra", 9)])

    assert result["missing"] == [leg("b", "missing", "2")]
    assert result["unexpected"] == [leg("b", "extra", "9")]
    assert result["quantity_mismatches"] == [leg("b", "mismatch", "3") | {"actual_quantity": "4"}]


def test_order_digest_and_inputs_are_deterministic_and_immutable_and_ignore_bin_contents():
    operations = all_kinds()
    operations[0]["bin"] = {"contents": {"not": "ledger input"}}
    holdings = [leg("batch", "one", 6), leg("batch", "two", 2), leg("batch", "three", 3)]
    before_operations, before_holdings = deepcopy(operations), deepcopy(holdings)

    first = compare_holdings_projection(operations, holdings)
    second = compare_holdings_projection(list(reversed(operations)), list(reversed(holdings)))

    assert first["is_consistent"] is second["is_consistent"] is True
    assert first["source_digest"] == second["source_digest"]
    assert first["missing"] == second["missing"] == []
    assert operations == before_operations
    assert holdings == before_holdings


def test_transfer_and_reduction_use_exact_decimal128_arithmetic_beyond_default_precision():
    large = "12345678901234567890123456789012"
    large_plus_one = "12345678901234567890123456789013"
    operations = [
        operation("receive-a", "receive", [leg("b", "source-a", large)]),
        operation("receive-b", "receive", [leg("b", "source-b", "1")]),
        operation("transfer", "transfer", [
            leg("b", "source-a", "-" + large),
            leg("b", "source-b", "-1"),
            leg("b", "target", large_plus_one),
        ]),
    ]

    result = compare_holdings_projection(operations, [
        leg("b", "source-a", "0"),
        leg("b", "source-b", "0"),
        leg("b", "target", large_plus_one),
    ])

    assert result["is_consistent"] is True
    assert result["malformed_facts"] == []


def test_digest_formats_supported_edge_exponents_and_rejects_overflow():
    supported = operation("maximum", "receive", [leg("b", "l", "1E+6144")])
    equivalent = operation(
        "maximum",
        "receive",
        [leg("b", "l", "1." + ("0" * 33) + "E+6144")],
    )
    first = compare_holdings_projection([supported], [leg("b", "l", "1E+6144")])
    second = compare_holdings_projection([equivalent], [leg("b", "l", "1E+6144")])

    assert first["is_consistent"] is second["is_consistent"] is True
    assert first["source_digest"] == second["source_digest"]

    overflow = compare_holdings_projection(
        [operation("overflow", "receive", [leg("b", "l", "1E+6145")])],
        [],
    )
    assert overflow["is_consistent"] is False
    assert overflow["malformed_facts"] == [{
        "operation_id": "overflow",
        "reason": "quantity overflows Decimal128",
    }]


def test_decimal128_arithmetic_rounding_and_overflow_fail_closed():
    maximum_coefficient = "9" * 34
    rounded = compare_holdings_projection([
        operation("first", "receive", [leg("b", "l", maximum_coefficient)]),
        operation("second", "receive", [leg("b", "l", "2")]),
    ], [])
    assert rounded["malformed_facts"] == [{
        "operation_id": "second",
        "reason": "quantity sum is not Decimal128-exact",
    }]

    overflow = compare_holdings_projection([
        operation("first", "receive", [leg("b", "l", ("9." + ("9" * 33) + "E+6144"))]),
        operation("second", "receive", [leg("b", "l", ("9." + ("9" * 33) + "E+6144"))]),
    ], [])
    assert overflow["malformed_facts"] == [{
        "operation_id": "second",
        "reason": "quantity sum overflows Decimal128",
    }]

    transfer = compare_holdings_projection([
        operation("transfer-rounding", "transfer", [
            leg("b", "a-credit", maximum_coefficient),
            leg("b", "b-credit", "2"),
            leg("b", "c-debit", "-" + maximum_coefficient),
            leg("b", "d-debit", "-2"),
        ]),
    ], [])
    assert transfer["malformed_facts"] == [{
        "operation_id": "transfer-rounding",
        "reason": "quantity sum is not Decimal128-exact",
    }]
