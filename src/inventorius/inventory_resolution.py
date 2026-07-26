"""Resolve scan and search evidence to concrete inventory batches.

This is deliberately separate from the general search endpoint.  Inventory
commands need a Batch, and a source-aware command may only select a positive,
unpackaged ``each`` holding from the append-only ledger projection.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import re

from bson.decimal128 import Decimal128

from inventorius.validation import normalize_prefixed_id


MAX_CONTEXT_MISMATCHES = 20
MAX_CONFLICT_BATCH_IDS = 20


def _match(
    evidence,
    *,
    kind,
    scope,
    relationship,
    resource_id,
    value,
):
    return {
        "evidence": evidence,
        "kind": kind,
        "scope": scope,
        "relationship": relationship,
        "resource_id": resource_id,
        "value": value,
    }


def _add_match(candidates, batch_id, match):
    if not batch_id:
        return
    key = tuple(match.items())
    matches = candidates[batch_id]
    if all(tuple(existing.items()) != key for existing in matches):
        matches.append(match)


def _claimant(scope, document):
    return {
        "scope": scope,
        "resource_id": document["_id"],
        "name": document.get("name"),
    }


def _exact_code_resolution(database, evidence):
    candidates = defaultdict(list)
    owned_claimants = []
    exact_found = False

    batch_documents = list(database.batch.find({"$or": [
        {"owned_codes": evidence},
        {"associated_codes": evidence},
    ]}))
    for batch_document in batch_documents:
        exact_found = True
        batch_id = batch_document["_id"]
        for relationship in ("owned", "associated"):
            if evidence in batch_document.get(f"{relationship}_codes", []):
                _add_match(candidates, batch_id, _match(
                    evidence,
                    kind="code",
                    scope="batch",
                    relationship=relationship,
                    resource_id=batch_id,
                    value=evidence,
                ))
                if relationship == "owned":
                    owned_claimants.append(_claimant("batch", batch_document))

    sku_documents = list(database.sku.find({"$or": [
        {"owned_codes": evidence},
        {"associated_codes": evidence},
    ]}))
    for sku_document in sku_documents:
        exact_found = True
        sku_id = sku_document["_id"]
        linked_batch_ids = [
            document["_id"]
            for document in database.batch.find({"sku_id": sku_id}, {"_id": 1})
        ]
        for relationship in ("owned", "associated"):
            if evidence not in sku_document.get(f"{relationship}_codes", []):
                continue
            match = _match(
                evidence,
                kind="code",
                scope="sku",
                relationship=relationship,
                resource_id=sku_id,
                value=evidence,
            )
            for batch_id in linked_batch_ids:
                _add_match(candidates, batch_id, match)
            if relationship == "owned":
                owned_claimants.append(_claimant("sku", sku_document))

    for observation in database.inventory_code_observations.find({"code": evidence}):
        exact_found = True
        batch_id = observation.get("batch_id")
        if database.batch.find_one({"_id": batch_id}, {"_id": 1}) is not None:
            _add_match(candidates, batch_id, _match(
                evidence,
                kind="code",
                scope="batch",
                relationship="observed",
                resource_id=batch_id,
                value=observation["code"],
            ))

    owned_claimants.sort(key=lambda claimant: (
        claimant["scope"], claimant["resource_id"]
    ))
    conflicts = []
    if len(owned_claimants) > 1:
        conflicts.append({
            "evidence": evidence,
            "kind": "duplicate-owned-code",
            "claimants": owned_claimants,
        })

    return candidates, exact_found, conflicts


def _text_resolution(database, evidence):
    """Return fragment matches without promoting resemblance to identity."""
    candidates = defaultdict(list)
    fragment = re.compile(re.escape(evidence), re.IGNORECASE)

    for batch_document in database.batch.find({"$or": [
        {"_id": fragment},
        {"name": fragment},
        {"owned_codes": fragment},
        {"associated_codes": fragment},
    ]}):
        batch_id = batch_document["_id"]
        if fragment.search(batch_id):
            _add_match(candidates, batch_id, _match(
                evidence,
                kind="text",
                scope="batch",
                relationship="identity",
                resource_id=batch_id,
                value=batch_id,
            ))
        name = batch_document.get("name")
        if isinstance(name, str) and fragment.search(name):
            _add_match(candidates, batch_id, _match(
                evidence,
                kind="text",
                scope="batch",
                relationship="name",
                resource_id=batch_id,
                value=name,
            ))
        for relationship in ("owned", "associated"):
            for value in batch_document.get(f"{relationship}_codes", []):
                if isinstance(value, str) and fragment.search(value):
                    _add_match(candidates, batch_id, _match(
                        evidence,
                        kind="text",
                        scope="batch",
                        relationship=relationship,
                        resource_id=batch_id,
                        value=value,
                    ))

    for sku_document in database.sku.find({"$or": [
        {"_id": fragment},
        {"name": fragment},
        {"owned_codes": fragment},
        {"associated_codes": fragment},
    ]}):
        sku_id = sku_document["_id"]
        matches = []
        if fragment.search(sku_id):
            matches.append(_match(
                evidence,
                kind="text",
                scope="sku",
                relationship="identity",
                resource_id=sku_id,
                value=sku_id,
            ))
        name = sku_document.get("name")
        if isinstance(name, str) and fragment.search(name):
            matches.append(_match(
                evidence,
                kind="text",
                scope="sku",
                relationship="name",
                resource_id=sku_id,
                value=name,
            ))
        for relationship in ("owned", "associated"):
            for value in sku_document.get(f"{relationship}_codes", []):
                if isinstance(value, str) and fragment.search(value):
                    matches.append(_match(
                        evidence,
                        kind="text",
                        scope="sku",
                        relationship=relationship,
                        resource_id=sku_id,
                        value=value,
                    ))
        for batch_document in database.batch.find({"sku_id": sku_id}, {"_id": 1}):
            for match in matches:
                _add_match(candidates, batch_document["_id"], match)

    for observation in database.inventory_code_observations.find({"code": fragment}):
        batch_id = observation.get("batch_id")
        if database.batch.find_one({"_id": batch_id}, {"_id": 1}) is not None:
            _add_match(candidates, batch_id, _match(
                evidence,
                kind="text",
                scope="batch",
                relationship="observed",
                resource_id=batch_id,
                value=observation["code"],
            ))

    return candidates


def _resolve_one(database, evidence):
    label_match = re.fullmatch(r"BAT[0-9]{1,6}", evidence, re.IGNORECASE)
    if label_match:
        batch_id = normalize_prefixed_id(evidence, "BAT")
        candidates = defaultdict(list)
        if database.batch.find_one({"_id": batch_id}, {"_id": 1}) is not None:
            _add_match(candidates, batch_id, _match(
                evidence,
                kind="batch-id",
                scope="batch",
                relationship="identity",
                resource_id=batch_id,
                value=batch_id,
            ))
        # BAT syntax is reserved for internal identity, even when an external
        # code happens to have the same bytes or the Batch does not exist.
        return candidates, True, []

    sku_label_match = re.fullmatch(r"SKU[0-9]{1,6}", evidence, re.IGNORECASE)
    if sku_label_match:
        sku_id = normalize_prefixed_id(evidence, "SKU")
        candidates = defaultdict(list)
        if database.sku.find_one({"_id": sku_id}, {"_id": 1}) is not None:
            for batch_document in database.batch.find({"sku_id": sku_id}, {"_id": 1}):
                _add_match(candidates, batch_document["_id"], _match(
                    evidence,
                    kind="sku-id",
                    scope="sku",
                    relationship="identity",
                    resource_id=sku_id,
                    value=sku_id,
                ))
        # Internal SKU spellings suppress external-code collisions even if no
        # Batch has been created for that product yet.
        return candidates, True, []

    candidates, exact_found, conflicts = _exact_code_resolution(database, evidence)
    if exact_found:
        return candidates, True, conflicts
    return _text_resolution(database, evidence), False, []


def _resolve_sku_one(database, evidence):
    """Resolve evidence directly to SKUs without expanding through Batches.

    This deliberately answers a different question from ``_resolve_one``.
    A receive may have enough evidence to identify the product family while
    still needing to create a new Batch, so linked Batch evidence must not
    manufacture a SKU candidate here.
    """
    label_match = re.fullmatch(r"SKU[0-9]{1,6}", evidence, re.IGNORECASE)
    if label_match:
        sku_id = normalize_prefixed_id(evidence, "SKU")
        candidates = defaultdict(list)
        if database.sku.find_one({"_id": sku_id}, {"_id": 1}) is not None:
            _add_match(candidates, sku_id, _match(
                evidence,
                kind="sku-id",
                scope="sku",
                relationship="identity",
                resource_id=sku_id,
                value=sku_id,
            ))
        # SKU syntax is reserved for an internal identity, exactly as BAT is
        # for Batch resolution.  It does not fall through to an external code.
        return candidates, True, []

    candidates = defaultdict(list)
    exact_found = False
    owned_claimants = []
    for sku_document in database.sku.find({"$or": [
        {"owned_codes": evidence},
        {"associated_codes": evidence},
    ]}):
        exact_found = True
        sku_id = sku_document["_id"]
        for relationship in ("owned", "associated"):
            if evidence in sku_document.get(f"{relationship}_codes", []):
                _add_match(candidates, sku_id, _match(
                    evidence,
                    kind="code",
                    scope="sku",
                    relationship=relationship,
                    resource_id=sku_id,
                    value=evidence,
                ))
                if relationship == "owned":
                    owned_claimants.append(_claimant("sku", sku_document))
    if exact_found:
        owned_claimants.sort(key=lambda claimant: claimant["resource_id"])
        conflicts = []
        if len(owned_claimants) > 1:
            conflicts.append({
                "evidence": evidence,
                "kind": "duplicate-owned-code",
                "claimants": owned_claimants,
            })
        return candidates, True, conflicts

    fragment = re.compile(re.escape(evidence), re.IGNORECASE)
    for sku_document in database.sku.find({"$or": [
        {"_id": fragment},
        {"name": fragment},
        {"owned_codes": fragment},
        {"associated_codes": fragment},
    ]}):
        sku_id = sku_document["_id"]
        if fragment.search(sku_id):
            _add_match(candidates, sku_id, _match(
                evidence,
                kind="text",
                scope="sku",
                relationship="identity",
                resource_id=sku_id,
                value=sku_id,
            ))
        name = sku_document.get("name")
        if isinstance(name, str) and fragment.search(name):
            _add_match(candidates, sku_id, _match(
                evidence,
                kind="text",
                scope="sku",
                relationship="name",
                resource_id=sku_id,
                value=name,
            ))
        for relationship in ("owned", "associated"):
            for value in sku_document.get(f"{relationship}_codes", []):
                if isinstance(value, str) and fragment.search(value):
                    _add_match(candidates, sku_id, _match(
                        evidence,
                        kind="text",
                        scope="sku",
                        relationship=relationship,
                        resource_id=sku_id,
                        value=value,
                    ))
    return candidates, False, []


def _decimal(value):
    if isinstance(value, Decimal128):
        return value.to_decimal()
    return Decimal(str(value))


def _json_quantity(value):
    value = _decimal(value)
    if value == value.to_integral_value():
        return int(value)
    return str(value)


def _source_holdings(database, source_location_id):
    eligible = defaultdict(Decimal)
    positive_at_source = set()
    for holding in database.inventory_holdings.find({
        "location_id": source_location_id,
        "quantity": {"$gt": Decimal128("0")},
    }):
        batch_id = holding.get("batch_id")
        if not batch_id:
            continue
        positive_at_source.add(batch_id)
        if (
            holding.get("unit") == "each"
            and holding.get("packaging_configuration_id") is None
        ):
            eligible[batch_id] += _decimal(holding["quantity"])
    return eligible, positive_at_source


_MATCH_STRENGTH = {
    ("batch-id", "batch", "identity"): 0,
    ("sku-id", "sku", "identity"): 1,
    ("code", "batch", "owned"): 2,
    ("code", "batch", "associated"): 3,
    ("code", "batch", "observed"): 4,
    ("code", "sku", "owned"): 5,
    ("code", "sku", "associated"): 6,
    ("text", "batch", "identity"): 7,
    ("text", "batch", "name"): 8,
    ("text", "sku", "identity"): 9,
    ("text", "sku", "name"): 10,
}


def _match_strength(match):
    return _MATCH_STRENGTH.get(
        (match["kind"], match["scope"], match["relationship"]),
        10,
    )


def _sort_matches(matches, evidence_order):
    return sorted(matches, key=lambda match: (
        evidence_order[match["evidence"]],
        _match_strength(match),
        match["scope"],
        match["relationship"],
        match["resource_id"],
        match["value"],
    ))


def _resolve_sku_candidates(database, evidence_values, *, limit, starting_from):
    """Return a parallel, direct-SKU resolution for receive flows.

    Unknown physical evidence is intentionally ignored here.  A scanned
    ``SKU1`` plus a previously unseen manufacturer code should identify the
    SKU and preserve that new code as observation on the newly created Batch;
    it should not turn a useful receive into a false conflict.
    """
    direct_terms = []
    unmatched_evidence = []
    conflicts = []
    for evidence in evidence_values:
        candidates, exact, term_conflicts = _resolve_sku_one(database, evidence)
        if candidates:
            direct_terms.append((evidence, candidates, exact))
        else:
            unmatched_evidence.append(evidence)
        conflicts.extend(term_conflicts)

    if direct_terms:
        global_ids = set(direct_terms[0][1])
        for _, candidates, _ in direct_terms[1:]:
            global_ids.intersection_update(candidates)
    else:
        global_ids = set()

    if len(direct_terms) > 1 and not global_ids:
        conflicts.append({
            "kind": "sku-evidence-conflict",
            "evidence": [evidence for evidence, _, _ in direct_terms],
            "candidate_sets": [
                {
                    "evidence": evidence,
                    "total_num_candidates": len(candidates),
                    "sku_ids": sorted(candidates)[:MAX_CONFLICT_BATCH_IDS],
                }
                for evidence, candidates, _ in direct_terms
            ],
        })

    evidence_order = {value: index for index, value in enumerate(evidence_values)}
    matches_by_sku = {
        sku_id: [
            match
            for _, candidates, _ in direct_terms
            for match in candidates[sku_id]
        ]
        for sku_id in global_ids
    }
    sku_documents = {
        document["_id"]: document
        for document in database.sku.find({"_id": {"$in": sorted(global_ids)}})
    }
    results = [
        {
            "sku_id": sku_id,
            "sku_name": sku_documents[sku_id].get("name"),
            "matches": _sort_matches(matches_by_sku[sku_id], evidence_order),
        }
        for sku_id in global_ids
        if sku_id in sku_documents
    ]

    def result_order(result):
        return (
            *[
                min(
                    _match_strength(match)
                    for match in result["matches"]
                    if match["evidence"] == evidence
                )
                for evidence, _, _ in direct_terms
            ],
            result["sku_id"],
        )

    results.sort(key=result_order)
    total_num_results = len(results)
    identifying = bool(results) and any(
        match["kind"] == "sku-id"
        or (
            match["kind"] == "code"
            and match["scope"] == "sku"
            and match["relationship"] == "owned"
        )
        for match in results[0]["matches"]
    )
    if conflicts:
        status = "conflict"
    elif not results:
        status = "unknown"
    elif len(results) == 1 and identifying:
        status = "identified"
    else:
        status = "candidates"

    resolution = (
        "none" if total_num_results == 0
        else "unique" if total_num_results == 1
        else "ambiguous"
    )
    paged_results = results[starting_from:(starting_from + limit)]
    return {
        "status": status,
        "resolution": resolution,
        "total_num_results": total_num_results,
        "starting_from": starting_from,
        "limit": limit,
        "returned_num_results": len(paged_results),
        "truncated": len(paged_results) < total_num_results,
        "results": paged_results,
        "conflicts": conflicts,
        "unmatched_evidence": unmatched_evidence,
    }


def resolve_inventory_candidates(
    database,
    evidence_values,
    source_location_id=None,
    *,
    limit=50,
    starting_from=0,
):
    """Resolve all evidence by set intersection and return an HTTP-ready state."""
    term_resolutions = []
    conflicts = []
    for evidence in evidence_values:
        candidates, exact, term_conflicts = _resolve_one(database, evidence)
        term_resolutions.append((candidates, exact))
        conflicts.extend(term_conflicts)

    if term_resolutions:
        global_ids = set(term_resolutions[0][0])
        for candidates, _ in term_resolutions[1:]:
            global_ids.intersection_update(candidates)
    else:
        global_ids = set()

    # Every term was understood, but no one Batch satisfies all of them.  That
    # is contradictory evidence, not an unknown scan.  Preserve the bounded
    # candidate sets so the UI can explain and let the user correct the input.
    if (
        len(term_resolutions) > 1
        and all(candidates for candidates, _ in term_resolutions)
        and not global_ids
    ):
        conflicts.append({
            "kind": "evidence-conflict",
            "evidence": list(evidence_values),
            "candidate_sets": [
                {
                    "evidence": evidence,
                    "total_num_candidates": len(candidates),
                    "batch_ids": sorted(candidates)[:MAX_CONFLICT_BATCH_IDS],
                }
                for evidence, (candidates, _) in zip(
                    evidence_values, term_resolutions
                )
            ],
        })

    all_exact = bool(term_resolutions) and all(
        exact for _, exact in term_resolutions
    )
    matches_by_batch = {}
    for batch_id in global_ids:
        matches_by_batch[batch_id] = [
            match
            for candidates, _ in term_resolutions
            for match in candidates[batch_id]
        ]

    eligible_quantities = None
    positive_at_source = set()
    if source_location_id is not None:
        eligible_quantities, positive_at_source = _source_holdings(
            database, source_location_id
        )
        result_ids = global_ids.intersection(eligible_quantities)
    else:
        result_ids = global_ids

    batch_documents = {
        document["_id"]: document
        for document in database.batch.find({"_id": {"$in": sorted(global_ids)}})
    }
    sku_ids = {
        document.get("sku_id")
        for document in batch_documents.values()
        if document.get("sku_id")
    }
    sku_documents = {
        document["_id"]: document
        for document in database.sku.find({"_id": {"$in": sorted(sku_ids)}})
    }

    evidence_order = {value: index for index, value in enumerate(evidence_values)}
    results = []
    for batch_id in result_ids:
        batch_document = batch_documents.get(batch_id)
        if batch_document is None:
            continue
        sku_id = batch_document.get("sku_id")
        sku_document = sku_documents.get(sku_id, {})
        result = {
            "batch_id": batch_id,
            "sku_id": sku_id,
            "batch_name": batch_document.get("name"),
            "sku_name": sku_document.get("name"),
            "unit": "each",
            "packaging_configuration_id": None,
            "available_quantity": None,
            "matches": _sort_matches(matches_by_batch[batch_id], evidence_order),
        }
        if eligible_quantities is not None:
            result["available_quantity"] = _json_quantity(
                eligible_quantities[batch_id]
            )
        results.append(result)

    def result_order(result):
        best_per_evidence = []
        for evidence in evidence_values:
            best_per_evidence.append(min(
                _match_strength(match)
                for match in result["matches"]
                if match["evidence"] == evidence
            ))
        return (*best_per_evidence, result["batch_id"])

    results.sort(key=result_order)

    context_mismatches = []
    # Source context is supposed to narrow shared evidence.  Only surface
    # filtered global matches when an otherwise exact resolution would have
    # become a generic empty result.
    if source_location_id is not None and not results and all_exact:
        for batch_id in sorted(global_ids):
            batch_document = batch_documents.get(batch_id)
            if batch_document is None or batch_id in eligible_quantities:
                continue
            sku_id = batch_document.get("sku_id")
            context_mismatches.append({
                "batch_id": batch_id,
                "sku_id": sku_id,
                "batch_name": batch_document.get("name"),
                "sku_name": sku_documents.get(sku_id, {}).get("name"),
                "reason": (
                    "unsupported-holding-shape"
                    if batch_id in positive_at_source
                    else "not-at-location"
                ),
            })

    total_num_results = len(results)
    globally_identifying_match = bool(results) and any(
        match["kind"] == "batch-id"
        or (
            match["kind"] == "code"
            and match["scope"] == "batch"
            and match["relationship"] == "owned"
        )
        for match in results[0]["matches"]
    )
    if conflicts:
        status = "conflict"
    elif not results:
        status = "unknown"
    elif (
        len(results) == 1
        and (
            globally_identifying_match
            or (source_location_id is not None and all_exact)
        )
    ):
        status = "identified"
    else:
        status = "candidates"

    resolution = (
        "none" if total_num_results == 0
        else "unique" if total_num_results == 1
        else "ambiguous"
    )
    paged_results = results[starting_from:(starting_from + limit)]
    return {
        "evidence": list(evidence_values),
        "source_location_id": source_location_id,
        "status": status,
        "resolution": resolution,
        "total_num_results": total_num_results,
        "starting_from": starting_from,
        "limit": limit,
        "returned_num_results": len(paged_results),
        "truncated": len(paged_results) < total_num_results,
        "results": paged_results,
        "conflicts": conflicts,
        "total_context_mismatches": len(context_mismatches),
        "context_mismatches": context_mismatches[:MAX_CONTEXT_MISMATCHES],
        # This is deliberately independent of source filtering.  A location
        # constrains selectable Batch holdings, not the SKU a physical code
        # describes.
        "sku_candidates": _resolve_sku_candidates(
            database,
            evidence_values,
            limit=limit,
            starting_from=starting_from,
        ),
    }
