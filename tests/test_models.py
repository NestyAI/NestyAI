from __future__ import annotations


def test_models_list_contains_aliases(client) -> None:
    response = client.get("/v1/models")
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    model_ids = {item["id"] for item in payload["data"]}
    assert "nesty-flash-1.0" in model_ids
    assert "nesty-combined-1.0" in model_ids
    assert "nesty-pro-1.0" in model_ids

