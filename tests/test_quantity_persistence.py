"""Lossless persistence and deterministic replay for quantity-native facts."""

from datetime import datetime, timezone
from fractions import Fraction

import pytest

from inventorius.ledger import HoldingKey
from inventorius.quantity_codec import (
    QuantityClaim,
    claim_document,
    claim_from_document,
    effect_from_document,
    observation_document,
    observation_from_document,
    opening_effect_document,
    output_state_id,
    rational_document,
    rational_from_document,
    withdrawal_effect_document,
)
from inventorius.quantity_constraints import ObservationBasis, QuantityDomain
from inventorius.quantity_projection import (
    QuantityProjectionError,
    compile_quantity_stream,
)


HOLDING = HoldingKey("BAT000001", "BIN000001", "each")
NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def operation(operation_id, effect):
    return {
        "_id": operation_id,
        "fact_id": operation_id,
        "fact_type": "inventory.operation",
        "envelope_version": 1,
        "fact_schema": {"name": "inventory.operation", "version": 2},
        "recorded_at": NOW,
        "quantity_effect": effect,
    }


def observation(observation_id, payload):
    return {
        "_id": observation_id,
        "fact_id": observation_id,
        "fact_type": "inventory.quantity-observation",
        "envelope_version": 1,
        "fact_schema": {
            "name": "inventory.quantity-observation",
            "version": 1,
        },
        "recorded_at": NOW,
        "observation": payload,
    }


def test_rational_codec_is_reduced_exact_and_rejects_noncanonical_forms():
    assert rational_document(Fraction(2, 6)) == {
        "numerator": "1", "denominator": "3"
    }
    assert rational_from_document(
        {"numerator": "-251", "denominator": "2"}, "amount"
    ) == Fraction(-251, 2)

    for malformed in (
        {"numerator": "2", "denominator": "6"},
        {"numerator": "01", "denominator": "2"},
        {"numerator": "1", "denominator": "0"},
        {"numerator": "+1", "denominator": "2"},
        {"numerator": "1", "denominator": "2", "derived": "0.5"},
    ):
        with pytest.raises(ValueError):
            rational_from_document(malformed, "amount")


def test_claim_codec_retains_capacity_and_arbitrary_fraction():
    claim = QuantityClaim(
        basis=ObservationBasis.MEASURED,
        lower=Fraction(1, 3),
        preferred=Fraction(1, 2),
        upper=Fraction(2, 3),
        capacity=1,
    )
    assert claim_from_document(claim_document(claim)) == claim
    assert "minimum" not in claim_document(claim)
    assert "solver" not in str(claim_document(claim))


def test_effect_and_observation_codecs_reject_unknown_fields_and_versions():
    opening = opening_effect_document(
        sequence=0,
        holding=HOLDING,
        domain=QuantityDomain.DISCRETE,
        output_state=output_state_id("OP" + "a" * 32, HOLDING),
        claim=QuantityClaim.estimated(50),
    )
    assert effect_from_document(opening).claim.preferred == 50

    bad = {**opening, "derived_bounds": {"minimum": 0, "maximum": 100}}
    with pytest.raises(ValueError, match="unexpected"):
        effect_from_document(bad)
    wrong_version = {
        **opening,
        "codec": {**opening["codec"], "version": 2},
    }
    with pytest.raises(ValueError, match="unsupported"):
        effect_from_document(wrong_version)

    payload = observation_document(
        sequence=1,
        holding=HOLDING,
        domain=QuantityDomain.DISCRETE,
        state_id=opening["output_state_id"],
        claim=QuantityClaim(
            basis=ObservationBasis.COUNTED,
            lower=60,
            preferred=60,
            upper=60,
        ),
    )
    assert observation_from_document(payload).claim.lower == 60


def test_replay_is_storage_order_independent_and_infers_opening_from_use_and_count():
    opening_id = "OP" + "a" * 32
    withdrawal_id = "OP" + "b" * 32
    observation_id = "QOB" + "c" * 32
    opening_state = output_state_id(opening_id, HOLDING)
    remaining_state = output_state_id(withdrawal_id, HOLDING)
    operations = [
        operation(
            opening_id,
            opening_effect_document(
                sequence=0,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                output_state=opening_state,
                claim=QuantityClaim.estimated(50),
            ),
        ),
        operation(
            withdrawal_id,
            withdrawal_effect_document(
                sequence=1,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                predecessor_state=opening_state,
                output_state=remaining_state,
                amount=Fraction(40),
            ),
        ),
    ]
    observations = [
        observation(
            observation_id,
            observation_document(
                sequence=2,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                state_id=remaining_state,
                claim=QuantityClaim(
                    basis=ObservationBasis.COUNTED,
                    lower=20,
                    preferred=20,
                    upper=20,
                ),
            ),
        )
    ]

    first = compile_quantity_stream(operations, observations)
    second = compile_quantity_stream(
        list(reversed(operations)), list(reversed(observations))
    )

    assert first.view == second.view == {
        "status": "feasible",
        "minimum": 20,
        "maximum": 20,
        "preferred": 20,
        "capacity": None,
        "unit": "each",
        "domain": "discrete",
        "conflict_fact_ids": [],
    }
    assert first.current_state_id == remaining_state


def test_conflicting_recount_is_retained_and_names_source_facts():
    opening_id = "OP" + "a" * 32
    withdrawal_id = "OP" + "b" * 32
    observation_id = "QOB" + "c" * 32
    opening_state = output_state_id(opening_id, HOLDING)
    remaining_state = output_state_id(withdrawal_id, HOLDING)
    compiled = compile_quantity_stream(
        [
            operation(
                opening_id,
                opening_effect_document(
                    sequence=0,
                    holding=HOLDING,
                    domain=QuantityDomain.DISCRETE,
                    output_state=opening_state,
                    claim=QuantityClaim(
                        basis=ObservationBasis.ESTIMATED,
                        lower=40,
                        preferred=50,
                        upper=60,
                    ),
                ),
            ),
            operation(
                withdrawal_id,
                withdrawal_effect_document(
                    sequence=1,
                    holding=HOLDING,
                    domain=QuantityDomain.DISCRETE,
                    predecessor_state=opening_state,
                    output_state=remaining_state,
                    amount=Fraction(40),
                ),
            ),
        ],
        [
            observation(
                observation_id,
                observation_document(
                    sequence=2,
                    holding=HOLDING,
                    domain=QuantityDomain.DISCRETE,
                    state_id=remaining_state,
                    claim=QuantityClaim(
                        basis=ObservationBasis.COUNTED,
                        lower=25,
                        preferred=25,
                        upper=25,
                    ),
                ),
            )
        ],
    )

    assert compiled.view["status"] == "conflict"
    assert set(compiled.view["conflict_fact_ids"]) == {
        opening_id, withdrawal_id, observation_id
    }


@pytest.mark.parametrize("mutation", ["gap", "fork", "dangling"])
def test_replay_fails_closed_for_ambiguous_state_history(mutation):
    opening_id = "OP" + "a" * 32
    withdrawal_id = "OP" + "b" * 32
    opening_state = output_state_id(opening_id, HOLDING)
    remaining_state = output_state_id(withdrawal_id, HOLDING)
    sequence = 2 if mutation == "gap" else 1
    predecessor = "QST" + "f" * 32 if mutation == "dangling" else opening_state
    operations = [
        operation(
            opening_id,
            opening_effect_document(
                sequence=0,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                output_state=opening_state,
                claim=QuantityClaim.estimated(50),
            ),
        ),
        operation(
            withdrawal_id,
            withdrawal_effect_document(
                sequence=sequence,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                predecessor_state=predecessor,
                output_state=remaining_state,
                amount=Fraction(1),
            ),
        ),
    ]
    if mutation == "fork":
        operations.append(operation(
            "OP" + "c" * 32,
            withdrawal_effect_document(
                sequence=1,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                predecessor_state=opening_state,
                output_state="QST" + "d" * 32,
                amount=Fraction(1),
            ),
        ))

    with pytest.raises(QuantityProjectionError):
        compile_quantity_stream(operations, [])


def test_supersession_keeps_bad_claim_but_excludes_it_from_feasibility():
    opening_id = "OP" + "a" * 32
    replacement_id = "QOB" + "b" * 32
    state = output_state_id(opening_id, HOLDING)
    compiled = compile_quantity_stream(
        [operation(
            opening_id,
            opening_effect_document(
                sequence=0,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                output_state=state,
                claim=QuantityClaim(
                    basis=ObservationBasis.ESTIMATED,
                    lower=40,
                    preferred=50,
                    upper=60,
                ),
            ),
        )],
        [observation(
            replacement_id,
            observation_document(
                sequence=1,
                holding=HOLDING,
                domain=QuantityDomain.DISCRETE,
                state_id=state,
                claim=QuantityClaim(
                    basis=ObservationBasis.COUNTED,
                    lower=20,
                    preferred=20,
                    upper=20,
                ),
                supersedes_fact_id=opening_id,
            ),
        )],
    )

    assert compiled.view["status"] == "feasible"
    assert compiled.view["minimum"] == compiled.view["maximum"] == 20
    by_id = {item["fact_id"]: item for item in compiled.history}
    assert by_id[opening_id]["active"] is False
    assert by_id[opening_id]["superseded_by_fact_id"] == replacement_id
