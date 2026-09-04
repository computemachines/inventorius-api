"""Authenticated HTTP contract for the non-persistent Solver Lab."""


ONE = {"numerator": "1", "denominator": "1"}


def query_request():
    return {
        "snapshot": {
            "revision": 3,
            "variables": [{
                "variable_id": "red",
                "unit": "each",
                "domain": "discrete",
            }],
            "constraints": [{
                "constraint_id": "red:exact",
                "coefficients": {"red": ONE},
                "relation": "equal",
                "bound": {"numerator": "25", "denominator": "1"},
            }],
        },
        "query": {
            "kind": "expression-bounds",
            "expression": {"red": ONE},
        },
    }


def test_solver_query_requires_an_authenticated_owner(anonymous_client):
    response = anonymous_client.post("/api/solver/query", json=query_request())

    assert response.status_code == 401
    assert response.json["type"] == "authentication-required"


def test_solver_lab_is_advertised_only_to_the_authenticated_owner(
    client, anonymous_client
):
    owner_operations = client.get("/api").json["operations"]
    anonymous_operations = anonymous_client.get("/api").json["operations"]

    assert {
        "rel": "solver-query",
        "method": "POST",
        "href": "/api/solver/query",
    } in owner_operations
    assert all(
        operation["rel"] != "solver-query"
        for operation in anonymous_operations
    )


def test_solver_query_returns_a_structured_fresh_answer(client):
    response = client.post("/api/solver/query", json=query_request())

    assert response.status_code == 200
    assert response.json == {"state": {"result": {
        "kind": "expression-bounds",
        "graph_revision": 3,
        "status": "solved",
        "unit": "each",
        "domain": "discrete",
        "bounds": {
            "minimum": {"numerator": "25", "denominator": "1"},
            "maximum": {"numerator": "25", "denominator": "1"},
        },
        "conflict_constraint_ids": [],
    }}}


def test_solver_query_reports_invalid_documents_without_mutating(client):
    response = client.post("/api/solver/query", json={"query": {}})

    assert response.status_code == 400
    assert response.json["invalid-params"][0]["name"] == "body"
