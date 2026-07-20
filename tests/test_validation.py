import pytest
from voluptuous import Invalid

from inventorius.validation import normalize_prefixed_id, prefixed_id


@pytest.mark.parametrize(
    ("entered", "canonical"),
    [
        ("BIN60", "BIN000060"),
        (" bin0060 ", "BIN000060"),
        ("SKU1", "SKU000001"),
        ("BAT999999", "BAT999999"),
    ],
)
def test_normalize_prefixed_id(entered, canonical):
    assert normalize_prefixed_id(entered, canonical[:3]) == canonical


def test_prefixed_id_validator_returns_canonical_value():
    assert prefixed_id("BIN")("BIN60") == "BIN000060"


@pytest.mark.parametrize("entered", ["BIN", "BIN1000000", "BIN12A", "SKU60"])
def test_normalize_prefixed_id_rejects_invalid_values(entered):
    with pytest.raises(Invalid):
        normalize_prefixed_id(entered, "BIN")


def test_user_url_id_rejects_non_alphanumeric_values(client):
    response = client.delete("/api/user/%3B")

    assert response.status_code == 400
    assert response.json["type"] == "validation-error"
