from __future__ import annotations

import time
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings
from app.storage.db import init_db
from app.storage.api_keys import get_api_key_by_id
from app.core.errors import APIError
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessage, GuardInfo, Usage
from app.schemas.tools import ToolMetadata


class _SuccessOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        return ChatCompletionResponse(
            id="chatcmpl_test",
            created=int(time.time()),
            model=request.model,
            provider="openrouter",
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Response content"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            guard=GuardInfo(),
            tools=ToolMetadata(),
            sources=[],
        )


@pytest.fixture
def mock_client(monkeypatch, tmp_path):
    from app.deps import get_settings
    db_path = str(tmp_path / "internal_api_keys_e2e.db")
    init_db(db_path)
    
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        internal_admin_enabled=True,
        nesty_internal_admin_token="admin-token",
        trusted_hosts="testserver",
        require_api_key=True,
        rate_limit_enabled=False,
        safe_debug_auth=True,
    )
    
    # Patch get_settings everywhere
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.internal_auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.internal_api_keys.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.conversations.get_settings", lambda: settings)
    
    # Mock orchestrator
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())
    
    get_settings.cache_clear()
    
    app = create_app(settings=settings)
    client = TestClient(app)
    return client, db_path, settings


# ==============================================================================
# TIER 1: Feature Coverage (>=5 cases per feature)
# ==============================================================================

# Feature 1: GET /internal/api-keys (List keys)

def test_t1_list_keys_empty(mock_client) -> None:
    """GET /internal/api-keys: list keys when none exist, returns 200 with empty list."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "limit": 50, "offset": 0, "has_more": False}


def test_t1_list_keys_with_data(mock_client) -> None:
    """GET /internal/api-keys: list keys returns all active and revoked keys."""
    client, _, _ = mock_client
    # Create a couple of keys
    client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key1"})
    client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key2"})
    resp = client.get("/internal/api-keys", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert {k["name"] for k in items} == {"key1", "key2"}


def test_t1_list_keys_filter_env(mock_client) -> None:
    """GET /internal/api-keys: filter by environment."""
    client, _, _ = mock_client
    client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key-dev", "environment": "dev"})
    client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key-live", "environment": "live"})
    
    resp_dev = client.get("/internal/api-keys?environment=dev", headers={"Authorization": "Bearer admin-token"})
    assert resp_dev.status_code == 200
    items_dev = resp_dev.json()["items"]
    assert len(items_dev) == 1
    assert items_dev[0]["name"] == "key-dev"
    
    resp_live = client.get("/internal/api-keys?environment=live", headers={"Authorization": "Bearer admin-token"})
    assert resp_live.status_code == 200
    items_live = resp_live.json()["items"]
    assert len(items_live) == 1
    assert items_live[0]["name"] == "key-live"


def test_t1_list_keys_filter_status(mock_client) -> None:
    """GET /internal/api-keys: filter by revoked status."""
    client, _, _ = mock_client
    # Create two keys, revoke one
    k1 = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key1"}).json()
    k2 = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key2"}).json()
    client.post(f"/internal/api-keys/{k1['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    
    # Query active (revoked=false)
    resp_active = client.get("/internal/api-keys?revoked=false", headers={"Authorization": "Bearer admin-token"})
    items_active = resp_active.json()["items"]
    assert len(items_active) == 1
    assert items_active[0]["id"] == k2["api_key"]["id"]
    
    # Query revoked (revoked=true)
    resp_revoked = client.get("/internal/api-keys?revoked=true", headers={"Authorization": "Bearer admin-token"})
    items_revoked = resp_revoked.json()["items"]
    assert len(items_revoked) == 1
    assert items_revoked[0]["id"] == k1["api_key"]["id"]


def test_t1_list_keys_search(mock_client) -> None:
    """GET /internal/api-keys: search keys by name query q."""
    client, _, _ = mock_client
    client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "apple-key"})
    client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "banana-key"})
    
    resp = client.get("/internal/api-keys?q=apple", headers={"Authorization": "Bearer admin-token"})
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "apple-key"


# Feature 2: POST /internal/api-keys (Create key)

def test_t1_create_key_basic(mock_client) -> None:
    """POST /internal/api-keys: create key with only name, other fields default."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "basic-key"})
    assert resp.status_code == 201
    data = resp.json()
    assert "api_key" in data
    assert "raw_key" in data
    
    api_key = data["api_key"]
    assert "id" in api_key
    assert api_key["name"] == "basic-key"
    assert api_key["environment"] == "prod"  # default is prod
    assert api_key["daily_limit"] is None
    assert api_key["monthly_limit"] is None
    assert api_key["models"] is None


def test_t1_create_key_with_env(mock_client) -> None:
    """POST /internal/api-keys: create key with explicit environment."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "live-key", "environment": "live"})
    assert resp.status_code == 201
    assert resp.json()["api_key"]["environment"] == "live"


def test_t1_create_key_with_limits(mock_client) -> None:
    """POST /internal/api-keys: create key with daily and monthly limits."""
    client, _, _ = mock_client
    resp = client.post(
        "/internal/api-keys",
        headers={"Authorization": "Bearer admin-token"},
        json={"name": "limited-key", "daily_limit": 50, "monthly_limit": 1000}
    )
    assert resp.status_code == 201
    api_key = resp.json()["api_key"]
    assert api_key["daily_limit"] == 50
    assert api_key["monthly_limit"] == 1000


def test_t1_create_key_with_models(mock_client) -> None:
    """POST /internal/api-keys: create key with specific allowed models."""
    client, _, _ = mock_client
    resp = client.post(
        "/internal/api-keys",
        headers={"Authorization": "Bearer admin-token"},
        json={"name": "model-key", "models": ["nesty-flash-1.0"]}
    )
    assert resp.status_code == 201
    assert resp.json()["api_key"]["models"] == ["nesty-flash-1.0"]


def test_t1_create_key_response_fields(mock_client) -> None:
    """POST /internal/api-keys: verify response fields omit key_hash and include raw_key."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "fields-key"})
    assert resp.status_code == 201
    data = resp.json()
    assert "raw_key" in data
    assert "api_key" in data
    assert "key_hash" not in data
    assert "key_hash" not in data["api_key"]


# Feature 3: GET /internal/api-keys/{id} (Get key detail)

def test_t1_get_key_exists(mock_client) -> None:
    """GET /internal/api-keys/{id}: get existing key metadata."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "get-key"}).json()
    resp = client.get(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 200
    assert resp.json()["id"] == k["api_key"]["id"]


def test_t1_get_key_not_found(mock_client) -> None:
    """GET /internal/api-keys/{id}: get non-existent key returns 404."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys/nonexistent-id", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "api_key_not_found"


def test_t1_get_key_fields_no_secrets(mock_client) -> None:
    """GET /internal/api-keys/{id}: verify response does not leak raw_key or key_hash."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "secret-key"}).json()
    resp = client.get(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"})
    data = resp.json()
    assert "raw_key" not in data
    assert "key_hash" not in data


def test_t1_get_key_state_active(mock_client) -> None:
    """GET /internal/api-keys/{id}: verify active state is returned correctly."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "active-key"}).json()
    resp = client.get(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"})
    assert resp.json()["is_revoked"] is False


def test_t1_get_key_state_revoked(mock_client) -> None:
    """GET /internal/api-keys/{id}: verify revoked state after revocation."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "revoked-key"}).json()
    client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    resp = client.get(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"})
    assert resp.json()["is_revoked"] is True
    assert resp.json()["revoked_at"] is not None


# Feature 4: POST /internal/api-keys/{id}/revoke (Revoke key)

def test_t1_revoke_key_success(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke: revoke active key."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "revoke-me"}).json()
    resp = client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={"reason": "rotated"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == k["api_key"]["id"]
    assert data["is_revoked"] is True
    assert data["reason"] == "rotated"


def test_t1_revoke_key_idempotent(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke: revoking multiple times is idempotent."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "revoke-idemp"}).json()
    r1 = client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    assert r1.status_code == 200
    r2 = client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    assert r2.status_code == 200


def test_t1_revoke_key_not_found(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke: revoking non-existent key returns 404."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys/nonexistent/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "api_key_not_found"


def test_t1_revoke_key_updates_is_active(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke: verify is_active updates in DB and GET."""
    client, db_path, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "revoke-db"}).json()
    client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    
    # Verify via storage layer
    record = get_api_key_by_id(db_path, k["api_key"]["id"])
    assert record["is_active"] == 0
    assert record["revoked_at"] is not None


def test_t1_revoke_key_prevents_use(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke: revoked key cannot be used for Chat API."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "revoke-use"}).json()
    raw_key = k["raw_key"]
    
    # Use active key -> should succeed (returns 200)
    chat_resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert chat_resp.status_code == 200
    
    # Revoke key
    client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    
    # Use revoked key -> should fail (returns 401)
    chat_resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert chat_resp.status_code == 401
    assert chat_resp.json()["error"]["code"] == "invalid_api_key"


# Feature 5: PATCH /internal/api-keys/{id} (Update key)

def test_t1_patch_key_name(mock_client) -> None:
    """PATCH /internal/api-keys/{id}: update key name."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "old-name"}).json()
    resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"}, json={"name": "new-name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-name"


def test_t1_patch_key_limits(mock_client) -> None:
    """PATCH /internal/api-keys/{id}: update key limits."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "old-limits"}).json()
    resp = client.patch(
        f"/internal/api-keys/{k['api_key']['id']}",
        headers={"Authorization": "Bearer admin-token"},
        json={"daily_limit": 80, "monthly_limit": 2000}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["daily_limit"] == 80
    assert data["monthly_limit"] == 2000


def test_t1_patch_key_models(mock_client) -> None:
    """PATCH /internal/api-keys/{id}: update allowed models."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "old-models", "models": ["nesty-flash-1.0"]}).json()
    resp = client.patch(
        f"/internal/api-keys/{k['api_key']['id']}",
        headers={"Authorization": "Bearer admin-token"},
        json={"models": ["nesty-flash-1.0", "nesty-combined-1.0"]}
    )
    assert resp.status_code == 200
    assert resp.json()["models"] == ["nesty-flash-1.0", "nesty-combined-1.0"]


def test_t1_patch_key_environment(mock_client) -> None:
    """PATCH /internal/api-keys/{id}: update environment."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "old-env", "environment": "dev"}).json()
    resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"}, json={"environment": "live"})
    assert resp.status_code == 200
    assert resp.json()["environment"] == "live"


def test_t1_patch_key_not_found(mock_client) -> None:
    """PATCH /internal/api-keys/{id}: patch non-existent key returns 404."""
    client, _, _ = mock_client
    resp = client.patch("/internal/api-keys/nonexistent", headers={"Authorization": "Bearer admin-token"}, json={"name": "hi"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "api_key_not_found"


# Feature 6: Security / Unauthorized / Error states

def test_t1_security_disabled_admin(mock_client, monkeypatch) -> None:
    """Security: when admin endpoints disabled, returns 404."""
    client, _, settings = mock_client
    # Disable admin
    settings.internal_admin_enabled = False
    monkeypatch.setattr("app.security.internal_auth.get_settings", lambda: settings)
    
    resp = client.get("/internal/api-keys", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "internal_admin_disabled"


def test_t1_security_enabled_missing_token(mock_client) -> None:
    """Security: missing Authorization token returns 401."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "internal_admin_unauthorized"


def test_t1_security_enabled_invalid_token(mock_client) -> None:
    """Security: invalid token in Authorization header returns 401."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "internal_admin_unauthorized"


def test_t1_security_incorrect_bearer_prefix(mock_client) -> None:
    """Security: basic prefix instead of Bearer returns 401."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": "Basic admin-token"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "internal_admin_unauthorized"


def test_t1_security_untrusted_host(mock_client, monkeypatch) -> None:
    """Security: request with untrusted host returns 400."""
    client, _, settings = mock_client
    # Let's restore real host middleware by setting trusted_hosts to ai.pr0w4.dev
    settings.trusted_hosts = "ai.pr0w4.dev"
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    from app.main import create_app
    app = create_app(settings=settings)
    from fastapi.testclient import TestClient
    client_host = TestClient(app)
    
    # A request with Host testserver will be rejected by TrustedHostMiddleware (returns 400)
    resp = client_host.get("/internal/api-keys", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 400


# ==============================================================================
# TIER 2: Boundary & Corner Cases (>=5 cases per feature)
# ==============================================================================

# Feature 1: GET /internal/api-keys (List boundary cases)

def test_t2_list_boundary_limit_zero(mock_client) -> None:
    """GET /internal/api-keys boundary: limit=0 is rejected (ge=1)."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys?limit=0", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_list_boundary_limit_negative(mock_client) -> None:
    """GET /internal/api-keys boundary: negative limit is rejected."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys?limit=-5", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_list_boundary_limit_too_high(mock_client) -> None:
    """GET /internal/api-keys boundary: limit > 200 is rejected (le=200)."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys?limit=201", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_list_boundary_offset_negative(mock_client) -> None:
    """GET /internal/api-keys boundary: negative offset is rejected."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys?offset=-1", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_list_boundary_invalid_params(mock_client) -> None:
    """GET /internal/api-keys boundary: invalid parameter types (non-integer pagination)."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys?limit=abc", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 422 or resp.status_code == 400


# Feature 2: POST /internal/api-keys (Create boundary cases)

def test_t2_create_boundary_empty_name(mock_client) -> None:
    """POST /internal/api-keys boundary: empty name is rejected."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": ""})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_create_boundary_whitespace_name(mock_client) -> None:
    """POST /internal/api-keys boundary: whitespace-only name is rejected."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "   "})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_create_boundary_negative_daily_limit(mock_client) -> None:
    """POST /internal/api-keys boundary: negative daily limit is rejected."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "test", "daily_limit": -1})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_create_boundary_negative_monthly_limit(mock_client) -> None:
    """POST /internal/api-keys boundary: negative monthly limit is rejected."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "test", "monthly_limit": -100})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_create_boundary_invalid_model(mock_client) -> None:
    """POST /internal/api-keys boundary: non-existent model alias is rejected."""
    client, _, _ = mock_client
    resp = client.post(
        "/internal/api-keys",
        headers={"Authorization": "Bearer admin-token"},
        json={"name": "test", "models": ["nonexistent-model"]}
    )
    assert resp.status_code == 422 or resp.status_code == 400


# Feature 3: GET /internal/api-keys/{id} (Get boundary cases)

def test_t2_get_boundary_empty_id(mock_client) -> None:
    """GET /internal/api-keys/{id} boundary: empty ID returns 404."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys/%20", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 404


def test_t2_get_boundary_sql_injection(mock_client) -> None:
    """GET /internal/api-keys/{id} boundary: SQL injection attempt handled safely."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys/' OR 1=1 --", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 404


def test_t2_get_boundary_extremely_long_id(mock_client) -> None:
    """GET /internal/api-keys/{id} boundary: extremely long ID is handled safely."""
    client, _, _ = mock_client
    resp = client.get(f"/internal/api-keys/{'a'*1000}", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 404


def test_t2_get_boundary_special_characters(mock_client) -> None:
    """GET /internal/api-keys/{id} boundary: special characters returns 404."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys/key$*#%^", headers={"Authorization": "Bearer admin-token"})
    assert resp.status_code == 404


def test_t2_get_boundary_case_sensitivity(mock_client) -> None:
    """GET /internal/api-keys/{id} boundary: ID lookup is case-sensitive (or safe)."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "case-test"}).json()
    upper_id = k["api_key"]["id"].upper()
    
    # If upper/lower changes the UUID or string ID, it shouldn't match
    if upper_id != k["api_key"]["id"]:
        resp = client.get(f"/internal/api-keys/{upper_id}", headers={"Authorization": "Bearer admin-token"})
        assert resp.status_code == 404


# Feature 4: POST /internal/api-keys/{id}/revoke (Revoke boundary cases)

def test_t2_revoke_boundary_invalid_id(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke boundary: invalid/empty ID returns 404."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys/%20/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    assert resp.status_code == 404


def test_t2_revoke_boundary_sql_injection(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke boundary: SQL injection attempt in ID."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys/' OR 1=1 --/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    assert resp.status_code == 404


def test_t2_revoke_boundary_extremely_long_id(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke boundary: extremely long ID in path."""
    client, _, _ = mock_client
    resp = client.post(f"/internal/api-keys/{'a'*1000}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    assert resp.status_code == 404


def test_t2_revoke_boundary_special_chars(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke boundary: special chars in ID."""
    client, _, _ = mock_client
    resp = client.post("/internal/api-keys/key@$%*/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
    assert resp.status_code == 404


def test_t2_revoke_boundary_already_revoked_multiple_times(mock_client) -> None:
    """POST /internal/api-keys/{id}/revoke boundary: multiple successive revocations."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "multi-rev"}).json()
    for _ in range(5):
        resp = client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers={"Authorization": "Bearer admin-token"}, json={})
        assert resp.status_code == 200


# Feature 5: PATCH /internal/api-keys/{id} (Update boundary cases)

def test_t2_patch_boundary_empty_name(mock_client) -> None:
    """PATCH /internal/api-keys/{id} boundary: update name to empty string is rejected."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key"}).json()
    resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"}, json={"name": ""})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_patch_boundary_negative_daily_limit(mock_client) -> None:
    """PATCH /internal/api-keys/{id} boundary: negative daily limit is rejected."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key"}).json()
    resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"}, json={"daily_limit": -10})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_patch_boundary_negative_monthly_limit(mock_client) -> None:
    """PATCH /internal/api-keys/{id} boundary: negative monthly limit is rejected."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key"}).json()
    resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"}, json={"monthly_limit": -500})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_patch_boundary_invalid_model(mock_client) -> None:
    """PATCH /internal/api-keys/{id} boundary: invalid model alias is rejected."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key"}).json()
    resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"}, json={"models": ["invalid-model"]})
    assert resp.status_code == 422 or resp.status_code == 400


def test_t2_patch_boundary_invalid_env(mock_client) -> None:
    """PATCH /internal/api-keys/{id} boundary: invalid environment is rejected."""
    client, _, _ = mock_client
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "key"}).json()
    resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers={"Authorization": "Bearer admin-token"}, json={"environment": "staging"})
    assert resp.status_code == 422 or resp.status_code == 400


# Feature 6: Security & Auth (Boundary boundary cases)

def test_t2_security_boundary_empty_bearer(mock_client) -> None:
    """Security boundary: Bearer prefix with empty token is rejected."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_t2_security_boundary_no_bearer_prefix(mock_client) -> None:
    """Security boundary: no space between Bearer prefix and token is rejected."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": "Beareradmin-token"})
    assert resp.status_code == 401


def test_t2_security_boundary_lowercase_bearer(mock_client) -> None:
    """Security boundary: lowercase bearer prefix should succeed."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": "bearer admin-token"})
    assert resp.status_code == 200


def test_t2_security_boundary_whitespace_token(mock_client) -> None:
    """Security boundary: token is just spaces is rejected."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": "Bearer    "})
    assert resp.status_code == 401


def test_t2_security_boundary_large_token(mock_client) -> None:
    """Security boundary: extremely large authorization header returns 401."""
    client, _, _ = mock_client
    resp = client.get("/internal/api-keys", headers={"Authorization": f"Bearer {'a'*5000}"})
    assert resp.status_code == 401


# ==============================================================================
# TIER 3: Cross-Feature Combination Cases (major feature flows)
# ==============================================================================

def test_t3_create_list_detail_flow(mock_client) -> None:
    """Tier 3: Create -> List -> Detail flow."""
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    # Create
    k = client.post("/internal/api-keys", headers=auth, json={"name": "flow-key"}).json()
    
    # List (verify present)
    l_resp = client.get("/internal/api-keys", headers=auth)
    names = {item["name"] for item in l_resp.json()["items"]}
    assert "flow-key" in names
    
    # Detail (verify match)
    d_resp = client.get(f"/internal/api-keys/{k['api_key']['id']}", headers=auth)
    assert d_resp.json()["name"] == "flow-key"


def test_t3_create_revoke_list_flow(mock_client) -> None:
    """Tier 3: Create -> Revoke -> List flow."""
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    # Create
    k = client.post("/internal/api-keys", headers=auth, json={"name": "flow-revoke"}).json()
    
    # Revoke
    client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers=auth, json={})
    
    # List active (should be empty)
    l_active = client.get("/internal/api-keys?revoked=false", headers=auth)
    assert not any(item["id"] == k["api_key"]["id"] for item in l_active.json()["items"])
    
    # List revoked (should contain key)
    l_revoked = client.get("/internal/api-keys?revoked=true", headers=auth)
    assert any(item["id"] == k["api_key"]["id"] for item in l_revoked.json()["items"])


def test_t3_create_patch_detail_flow(mock_client) -> None:
    """Tier 3: Create -> Patch -> Detail flow."""
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    # Create
    k = client.post("/internal/api-keys", headers=auth, json={"name": "patch-flow"}).json()
    
    # Patch
    client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers=auth, json={"name": "patched-flow-name", "daily_limit": 99})
    
    # Detail (verify fields are updated)
    d_resp = client.get(f"/internal/api-keys/{k['api_key']['id']}", headers=auth)
    data = d_resp.json()
    assert data["name"] == "patched-flow-name"
    assert data["daily_limit"] == 99


def test_t3_create_revoke_revoke_idempotency(mock_client) -> None:
    """Tier 3: Create -> Revoke -> Revoke flow (idempotency)."""
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    k = client.post("/internal/api-keys", headers=auth, json={"name": "flow-double-rev"}).json()
    
    r1 = client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers=auth, json={})
    assert r1.status_code == 200
    
    r2 = client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers=auth, json={})
    assert r2.status_code == 200


def test_t3_create_revoke_patch_flow(mock_client) -> None:
    """Tier 3: Create -> Revoke -> Patch flow (revoked keys can still be patched/renamed)."""
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    k = client.post("/internal/api-keys", headers=auth, json={"name": "rev-patch"}).json()
    client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers=auth, json={})
    
    # Patching
    p_resp = client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers=auth, json={"name": "patched-rev-name"})
    assert p_resp.status_code == 200
    assert p_resp.json()["name"] == "patched-rev-name"


# ==============================================================================
# TIER 4: Real-World Application Scenarios (Gateway & Console Interactions)
# ==============================================================================

def test_t4_key_lifecycle_full_workflow(mock_client) -> None:
    """Tier 4: Complete end-to-end lifecycle workflow.
    Admin creates key -> client makes chat requests -> Admin updates daily limit -> client requests -> Admin revokes key -> client rejected.
    """
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    # 1. Admin creates API key
    k = client.post("/internal/api-keys", headers=auth, json={
        "name": "lifecycle-key",
        "daily_limit": 10,
        "models": ["nesty-flash-1.0"]
    }).json()
    raw_key = k["raw_key"]
    
    # 2. Client uses it for chat
    chat_resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "hello"}]}
    )
    assert chat_resp.status_code == 200
    
    # 3. Admin updates daily limit to 1
    client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers=auth, json={"daily_limit": 1})
    
    # 4. Client does a second request -> blocked by daily quota
    chat_resp2 = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "hello again"}]}
    )
    assert chat_resp2.status_code == 429
    assert chat_resp2.json()["error"]["code"] == "daily_quota_exceeded"
    
    # 5. Admin updates limit back to 10
    client.patch(f"/internal/api-keys/{k['api_key']['id']}", headers=auth, json={"daily_limit": 10})
    
    # 6. Admin revokes key
    client.post(f"/internal/api-keys/{k['api_key']['id']}/revoke", headers=auth, json={})
    
    # 7. Client gets rejected
    chat_resp3 = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "hello after revoke"}]}
    )
    assert chat_resp3.status_code == 401
    assert chat_resp3.json()["error"]["code"] == "invalid_api_key"


def test_t4_quota_limits_blocking(mock_client) -> None:
    """Tier 4: Validate daily and monthly quota limits blocking Chat API."""
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    # Case A: Daily limit exceeded
    k_daily = client.post("/internal/api-keys", headers=auth, json={
        "name": "daily-limit-test",
        "daily_limit": 1
    }).json()
    # First request
    r1 = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {k_daily['raw_key']}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "a"}]}
    )
    assert r1.status_code == 200
    # Second request -> blocked
    r2 = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {k_daily['raw_key']}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "b"}]}
    )
    assert r2.status_code == 429
    assert r2.json()["error"]["code"] == "daily_quota_exceeded"
    
    # Case B: Monthly limit exceeded
    k_monthly = client.post("/internal/api-keys", headers=auth, json={
        "name": "monthly-limit-test",
        "monthly_limit": 1
    }).json()
    # First request
    r3 = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {k_monthly['raw_key']}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "c"}]}
    )
    assert r3.status_code == 200
    # Second request -> blocked
    r4 = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {k_monthly['raw_key']}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "d"}]}
    )
    assert r4.status_code == 429
    assert r4.json()["error"]["code"] == "monthly_quota_exceeded"


def test_t4_model_restrictions_blocking(mock_client) -> None:
    """Tier 4: Validate allowed_models restrictions blocking Chat API."""
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    # Key allowed only for nesty-flash-1.0
    k = client.post("/internal/api-keys", headers=auth, json={
        "name": "model-restrict-key",
        "models": ["nesty-flash-1.0"]
    }).json()
    raw_key = k["raw_key"]
    
    # Request nesty-flash-1.0 -> success
    r_ok = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "hello"}]}
    )
    assert r_ok.status_code == 200
    
    # Request nesty-combined-1.0 -> blocked
    r_bad = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hello"}]}
    )
    assert r_bad.status_code == 403
    assert r_bad.json()["error"]["code"] == "model_not_allowed"


def test_t4_multi_environment_isolation(mock_client) -> None:
    """Tier 4: Validate environment prefixing and database query filtering.
    Ensure 'dev' and 'live' keys are correctly prefix-validated and isolated in status lists.
    """
    client, _, _ = mock_client
    auth = {"Authorization": "Bearer admin-token"}
    
    # Create a dev key
    k_dev = client.post("/internal/api-keys", headers=auth, json={
        "name": "dev-env-key",
        "environment": "dev"
    }).json()
    assert k_dev["raw_key"].startswith("nsk_dev_")
    
    # Create a live key
    k_live = client.post("/internal/api-keys", headers=auth, json={
        "name": "live-env-key",
        "environment": "live"
    }).json()
    assert k_live["raw_key"].startswith("nsk_live_")
    
    # Validate filtering isolation
    dev_list = client.get("/internal/api-keys?environment=dev", headers=auth).json()["items"]
    assert any(item["id"] == k_dev["api_key"]["id"] for item in dev_list)
    assert not any(item["id"] == k_live["api_key"]["id"] for item in dev_list)
    
    live_list = client.get("/internal/api-keys?environment=live", headers=auth).json()["items"]
    assert any(item["id"] == k_live["api_key"]["id"] for item in live_list)
    assert not any(item["id"] == k_dev["api_key"]["id"] for item in live_list)


# Test 7: Public API Key cannot access internal endpoints
def test_public_key_cannot_access_internal_endpoints(mock_client) -> None:
    """Validate that a valid public API key cannot access internal api-keys endpoints."""
    client, _, _ = mock_client
    # 1. Create a public API key using admin token
    k = client.post("/internal/api-keys", headers={"Authorization": "Bearer admin-token"}, json={"name": "public-access"}).json()
    public_raw_key = k["raw_key"]
    
    # 2. Try to list keys with public key in Authorization header -> should fail with 401
    resp = client.get("/internal/api-keys", headers={"Authorization": f"Bearer {public_raw_key}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "internal_admin_unauthorized"
