"""HTTP proofs for contextual evidence-to-Batch resolution."""

from bson.decimal128 import Decimal128
import pytest

from tests.database import get_test_database


@pytest.fixture(autouse=True)
def inventory_database():
    database = get_test_database()
    collections = (
        database.batch,
        database.bin,
        database.inventory_code_observations,
        database.inventory_holdings,
        database.sku,
    )
    for collection in collections:
        collection.delete_many({})
    database.bin.insert_many([
        {"_id": "BIN000001", "contents": {}, "props": {}},
        {"_id": "BIN000002", "contents": {}, "props": {}},
    ])
    yield database
    for collection in collections:
        collection.delete_many({})


def insert_sku(database, sku_id, name=None, owned=(), associated=()):
    database.sku.insert_one({
        "_id": sku_id,
        "name": name,
        "owned_codes": list(owned),
        "associated_codes": list(associated),
        "props": {},
    })


def insert_batch(
    database,
    batch_id,
    *,
    sku_id=None,
    name=None,
    owned=(),
    associated=(),
):
    database.batch.insert_one({
        "_id": batch_id,
        "sku_id": sku_id,
        "name": name,
        "owned_codes": list(owned),
        "associated_codes": list(associated),
        "props": {},
    })


def insert_holding(
    database,
    batch_id,
    location_id="BIN000001",
    quantity="1",
    unit="each",
    packaging_configuration_id=None,
):
    database.inventory_holdings.insert_one({
        "batch_id": batch_id,
        "location_id": location_id,
        "quantity": Decimal128(quantity),
        "unit": unit,
        "packaging_configuration_id": packaging_configuration_id,
    })


def resolve(client, *evidence, source=None):
    query = [("evidence", value) for value in evidence]
    if source is not None:
        query.append(("source_location_id", source))
    return client.get("/api/inventory-candidates", query_string=query)


def test_empty_request_is_an_empty_resolution(client):
    response = resolve(client)

    assert response.status_code == 200
    assert response.json["state"] == {
        "evidence": [],
        "source_location_id": None,
        "status": "unknown",
        "resolution": "none",
        "total_num_results": 0,
        "starting_from": 0,
        "limit": 50,
        "returned_num_results": 0,
        "truncated": False,
        "results": [],
        "conflicts": [],
        "total_context_mismatches": 0,
        "context_mismatches": [],
    }


def test_batch_label_is_normalized_and_reserved_before_external_codes(
    client, inventory_database
):
    insert_batch(inventory_database, "BAT000001", name="Intended batch")
    insert_batch(
        inventory_database,
        "BAT000002",
        name="External collision",
        owned=("BAT000001",),
    )

    response = resolve(client, "bat1")

    assert response.status_code == 200
    state = response.json["state"]
    assert state["status"] == "identified"
    assert state["resolution"] == "unique"
    assert [candidate["batch_id"] for candidate in state["results"]] == [
        "BAT000001"
    ]
    assert state["results"][0]["matches"] == [{
        "evidence": "bat1",
        "kind": "batch-id",
        "scope": "batch",
        "relationship": "identity",
        "resource_id": "BAT000001",
        "value": "BAT000001",
    }]
    assert state["results"][0]["available_quantity"] is None


def test_exact_code_suppresses_coincidental_text_and_preserves_provenance(
    client, inventory_database
):
    insert_batch(
        inventory_database,
        "BAT000001",
        name="Ordinary part",
        associated=("GLUE",),
    )
    insert_batch(inventory_database, "BAT000002", name="Glue applicator")

    response = resolve(client, "GLUE")

    state = response.json["state"]
    assert state["status"] == "candidates"
    assert [candidate["batch_id"] for candidate in state["results"]] == [
        "BAT000001"
    ]
    assert state["results"][0]["matches"][0]["relationship"] == "associated"
    assert state["results"][0]["matches"][0]["kind"] == "code"


def test_sku_evidence_expands_to_concrete_batches_and_source_narrows_it(
    client, inventory_database
):
    insert_sku(
        inventory_database,
        "SKU000001",
        name="Glue sticks",
        owned=("026000005623",),
    )
    insert_batch(inventory_database, "BAT000001", sku_id="SKU000001")
    insert_batch(inventory_database, "BAT000002", sku_id="SKU000001")
    insert_holding(inventory_database, "BAT000002", quantity="4")

    global_response = resolve(client, "026000005623")
    source_response = resolve(client, "026000005623", source="BIN1")

    assert global_response.json["state"]["resolution"] == "ambiguous"
    assert [row["batch_id"] for row in global_response.json["state"]["results"]] == [
        "BAT000001",
        "BAT000002",
    ]
    source_state = source_response.json["state"]
    assert source_state["status"] == "identified"
    assert source_state["source_location_id"] == "BIN000001"
    assert source_state["results"][0]["batch_id"] == "BAT000002"
    assert source_state["results"][0]["available_quantity"] == 4
    assert source_state["results"][0]["matches"][0]["resource_id"] == "SKU000001"


def test_multiple_evidence_values_intersect_candidate_sets(
    client, inventory_database
):
    insert_sku(
        inventory_database,
        "SKU000001",
        name="Connector assortment",
        associated=("SHARED-SKU",),
    )
    insert_batch(
        inventory_database,
        "BAT000001",
        sku_id="SKU000001",
        associated=("BLUE-BAG",),
    )
    insert_batch(
        inventory_database,
        "BAT000002",
        sku_id="SKU000001",
        associated=("RED-BAG",),
    )
    insert_holding(inventory_database, "BAT000001")

    response = resolve(client, "SHARED-SKU", "BLUE-BAG", source="BIN1")
    reverse_response = resolve(client, "BLUE-BAG", "SHARED-SKU", source="BIN1")

    state = response.json["state"]
    assert state["status"] == "identified"
    assert state["evidence"] == ["SHARED-SKU", "BLUE-BAG"]
    assert [row["batch_id"] for row in state["results"]] == ["BAT000001"]
    assert reverse_response.json["state"]["status"] == "identified"
    assert [
        row["batch_id"] for row in reverse_response.json["state"]["results"]
    ] == ["BAT000001"]
    assert [match["evidence"] for match in state["results"][0]["matches"]] == [
        "SHARED-SKU",
        "BLUE-BAG",
    ]


def test_narrowing_exact_code_needs_source_context_to_identify(
    client, inventory_database
):
    insert_batch(
        inventory_database,
        "BAT000001",
        name="Only global candidate",
        associated=("NARROWING-CODE",),
    )
    insert_holding(inventory_database, "BAT000001")

    global_response = resolve(client, "NARROWING-CODE")
    source_response = resolve(client, "NARROWING-CODE", source="BIN1")

    assert global_response.json["state"]["resolution"] == "unique"
    assert global_response.json["state"]["status"] == "candidates"
    assert source_response.json["state"]["resolution"] == "unique"
    assert source_response.json["state"]["status"] == "identified"


def test_uniquely_claimed_batch_owned_code_can_identify_globally(
    client, inventory_database
):
    insert_batch(
        inventory_database,
        "BAT000001",
        owned=("BATCH-IDENTITY",),
    )

    response = resolve(client, "BATCH-IDENTITY")

    assert response.json["state"]["resolution"] == "unique"
    assert response.json["state"]["status"] == "identified"


def test_duplicate_owned_claims_are_a_visible_conflict_even_after_narrowing(
    client, inventory_database
):
    insert_sku(
        inventory_database,
        "SKU000001",
        name="Claim one",
        owned=("DUPLICATE",),
    )
    insert_batch(
        inventory_database,
        "BAT000001",
        sku_id="SKU000001",
        associated=("FIRST",),
    )
    insert_batch(
        inventory_database,
        "BAT000002",
        name="Claim two",
        owned=("DUPLICATE",),
        associated=("SECOND",),
    )

    response = resolve(client, "DUPLICATE", "FIRST")

    state = response.json["state"]
    assert state["resolution"] == "unique"
    assert state["status"] == "conflict"
    assert state["results"][0]["batch_id"] == "BAT000001"
    assert state["conflicts"] == [{
        "evidence": "DUPLICATE",
        "kind": "duplicate-owned-code",
        "claimants": [
            {
                "scope": "batch",
                "resource_id": "BAT000002",
                "name": "Claim two",
            },
            {
                "scope": "sku",
                "resource_id": "SKU000001",
                "name": "Claim one",
            },
        ],
    }]


def test_shared_observation_is_contextually_identified_without_duplicates(
    client, inventory_database
):
    insert_batch(inventory_database, "BAT000001")
    insert_batch(inventory_database, "BAT000002")
    inventory_database.inventory_code_observations.insert_many([
        {"_id": "OBS1", "code": "SCAN", "batch_id": "BAT000001"},
        {"_id": "OBS2", "code": "SCAN", "batch_id": "BAT000001"},
        {"_id": "OBS3", "code": "SCAN", "batch_id": "BAT000002"},
    ])
    insert_holding(inventory_database, "BAT000002")

    response = resolve(client, "SCAN", source="BIN000001")

    result = response.json["state"]["results"][0]
    assert result["batch_id"] == "BAT000002"
    assert len(result["matches"]) == 1
    assert result["matches"][0]["relationship"] == "observed"


def test_text_fragment_from_linked_sku_is_never_silently_identified(
    client, inventory_database
):
    insert_sku(inventory_database, "SKU000001", name="Handheld multimeter")
    insert_batch(inventory_database, "BAT000001", sku_id="SKU000001")
    insert_holding(inventory_database, "BAT000001")

    response = resolve(client, "hand", source="BIN1")

    state = response.json["state"]
    assert state["resolution"] == "unique"
    assert state["status"] == "candidates"
    assert state["results"][0]["matches"][0] == {
        "evidence": "hand",
        "kind": "text",
        "scope": "sku",
        "relationship": "name",
        "resource_id": "SKU000001",
        "value": "Handheld multimeter",
    }


def test_text_search_treats_regex_punctuation_literally(
    client, inventory_database
):
    insert_batch(inventory_database, "BAT000001", name="Bracket [left]")
    insert_batch(inventory_database, "BAT000002", name="Bracket right")

    response = resolve(client, "[left]")

    assert [row["batch_id"] for row in response.json["state"]["results"]] == [
        "BAT000001"
    ]


def test_source_uses_only_positive_each_unpacked_ledger_holdings(
    client, inventory_database
):
    for number in range(1, 5):
        insert_batch(inventory_database, f"BAT{number:06}", name="Matched part")
    insert_holding(inventory_database, "BAT000001", quantity="3")
    insert_holding(inventory_database, "BAT000002", quantity="0")
    insert_holding(inventory_database, "BAT000003", unit="case")
    insert_holding(
        inventory_database,
        "BAT000004",
        packaging_configuration_id="PKG000001",
    )
    # Legacy contents are intentionally not a source of selectable inventory.
    inventory_database.bin.update_one(
        {"_id": "BIN000001"},
        {"$set": {"contents.BAT000002": 99}},
    )

    response = resolve(client, "Matched", source="BIN1")

    assert [row["batch_id"] for row in response.json["state"]["results"]] == [
        "BAT000001"
    ]


@pytest.mark.parametrize(
    "holding, expected_reason",
    [
        (None, "not-at-location"),
        ({"unit": "case", "packaging_configuration_id": None},
         "unsupported-holding-shape"),
    ],
)
def test_exact_match_filtered_from_source_explains_the_context_mismatch(
    client, inventory_database, holding, expected_reason
):
    insert_batch(inventory_database, "BAT000001", associated=("EXACT",))
    if holding is not None:
        insert_holding(inventory_database, "BAT000001", **holding)

    response = resolve(client, "EXACT", source="BIN1")

    state = response.json["state"]
    assert state["status"] == "unknown"
    assert state["results"] == []
    assert state["total_context_mismatches"] == 1
    assert state["context_mismatches"][0]["batch_id"] == "BAT000001"
    assert state["context_mismatches"][0]["reason"] == expected_reason


@pytest.mark.parametrize(
    "query, expected_name, expected_status",
    [
        ([('evidence', '')], "evidence", 400),
        ([('evidence', 'ABC\nDEF')], "evidence", 400),
        ([('evidence', 'X' * 501)], "evidence", 400),
        ([('evidence', 'ok'), ('source_location_id', 'BIN1'),
          ('source_location_id', 'BIN2')], "source_location_id", 400),
        ([('evidence', 'ok'), ('source_location_id', 'warehouse')],
         "source_location_id", 400),
    ],
)
def test_query_validation(client, query, expected_name, expected_status):
    response = client.get("/api/inventory-candidates", query_string=query)

    assert response.status_code == expected_status
    assert response.json["invalid-params"][0]["name"] == expected_name


def test_evidence_count_is_bounded_and_duplicate_values_are_deduplicated(
    client, inventory_database
):
    too_many = client.get(
        "/api/inventory-candidates",
        query_string=[("evidence", f"code-{index}") for index in range(51)],
    )
    assert too_many.status_code == 400
    assert too_many.json["invalid-params"][0]["name"] == "evidence"

    insert_batch(inventory_database, "BAT000001", associated=("SAME",))
    deduplicated = resolve(client, "SAME", "SAME")
    assert deduplicated.status_code == 200
    assert deduplicated.json["state"]["evidence"] == ["SAME"]
    assert deduplicated.json["state"]["status"] == "candidates"


def test_missing_source_bin_is_not_treated_as_empty_inventory(client):
    response = resolve(client, "anything", source="BIN999999")

    assert response.status_code == 404
    assert response.json["type"] == "missing-resource"


def test_results_are_deterministic_by_strength_then_batch_id(
    client, inventory_database
):
    insert_batch(inventory_database, "BAT000003", name="Common part")
    insert_batch(inventory_database, "BAT000001", name="Common part")
    insert_batch(inventory_database, "BAT000002", name="Common part")

    response = resolve(client, "Common")

    assert response.json["state"]["resolution"] == "ambiguous"
    assert [row["batch_id"] for row in response.json["state"]["results"]] == [
        "BAT000001",
        "BAT000002",
        "BAT000003",
    ]


def test_disjoint_known_evidence_is_a_conflict_not_an_unknown_scan(
    client, inventory_database
):
    insert_batch(inventory_database, "BAT000001", associated=("FIRST",))
    insert_batch(inventory_database, "BAT000002", associated=("SECOND",))

    response = resolve(client, "FIRST", "SECOND")

    state = response.json["state"]
    assert state["status"] == "conflict"
    assert state["resolution"] == "none"
    assert state["conflicts"] == [{
        "kind": "evidence-conflict",
        "evidence": ["FIRST", "SECOND"],
        "candidate_sets": [
            {
                "evidence": "FIRST",
                "total_num_candidates": 1,
                "batch_ids": ["BAT000001"],
            },
            {
                "evidence": "SECOND",
                "total_num_candidates": 1,
                "batch_ids": ["BAT000002"],
            },
        ],
    }]


def test_candidate_limit_is_bounded_after_ambiguity_is_computed(
    client, inventory_database
):
    for number in range(1, 4):
        insert_batch(
            inventory_database,
            f"BAT{number:06}",
            name="Common part",
        )

    response = client.get(
        "/api/inventory-candidates",
        query_string={"evidence": "Common", "limit": 1, "starting_from": 1},
    )

    state = response.json["state"]
    assert state["status"] == "candidates"
    assert state["resolution"] == "ambiguous"
    assert state["total_num_results"] == 3
    assert state["returned_num_results"] == 1
    assert state["truncated"] is True
    assert [row["batch_id"] for row in state["results"]] == ["BAT000002"]
