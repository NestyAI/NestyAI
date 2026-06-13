from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, OrchestrationRoleConfig, ProviderTarget, Settings
from app.core.model_config_loader import (
    merge_orchestration_roles_override,
    validate_model_config_override,
)
from app.core.multi_model_orchestrator import NestyProMultiModelOrchestrator, should_use_orchestration
from app.core.orchestration_roles import (
    DEFAULT_ROLE_MAX_TOKENS,
    resolve_effective_role_config,
    select_roles_for_run,
)
from app.schemas.provider import ProviderChatResult, ProviderUsage
from app.storage.db import init_db


def _admin_headers(token: str = "admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _console_settings(db_path: str):
    return type(
        "S",
        (),
        {
            "internal_admin_enabled": True,
            "nesty_internal_admin_token": "admin-token",
            "nesty_console_client_auth_required": False,
            "nesty_db_path": db_path,
            "require_api_key": False,
            "public_models": True,
            "public_health": True,
            "trusted_hosts": "testserver",
            "groq_api_key": "test-groq",
            "openrouter_api_key": "test-openrouter",
            "nvidia_api_key": None,
            "ollama_api_key": None,
            "deepseek_api_key": None,
            "openai_api_key": None,
            "mistral_api_key": None,
            "z_ai_api_key": None,
            "google_gemini_api_key": None,
            "anthropic_claude_api_key": None,
        },
    )()


def test_orchestration_role_config_parses_extended_fields() -> None:
    role = OrchestrationRoleConfig(
        enabled=True,
        provider_chain=[ProviderTarget(provider="groq", model="llama-3.3-70b-versatile")],
        temperature=0.3,
        max_tokens=512,
        timeout_seconds=45.0,
    )
    assert role.enabled is True
    assert role.temperature == 0.3
    assert role.max_tokens == 512
    assert role.timeout_seconds == 45.0


def test_validate_rejects_invalid_role_id() -> None:
    valid, error = validate_model_config_override(
        "nesty-pro-1.0",
        {"orchestration_roles": {"verifier": {"provider_chain": [{"provider": "groq", "model": "x"}]}}},
    )
    assert valid is False
    assert "invalid orchestration role" in (error or "")


def test_validate_rejects_disabling_required_role() -> None:
    valid, error = validate_model_config_override(
        "nesty-pro-1.0",
        {"orchestration_roles": {"planner": {"enabled": False}}},
    )
    assert valid is False
    assert "cannot be disabled" in (error or "")


def test_validate_accepts_role_execution_fields() -> None:
    valid, error = validate_model_config_override(
        "nesty-pro-1.0",
        {
            "orchestration_roles": {
                "finalizer": {
                    "temperature": 0.4,
                    "max_tokens": 1600,
                    "timeout_seconds": 60,
                    "provider_chain": [{"provider": "groq", "model": "llama-3.3-70b-versatile"}],
                }
            }
        },
    )
    assert valid is True
    assert error is None


def test_validate_rejects_out_of_range_role_temperature() -> None:
    valid, error = validate_model_config_override(
        "nesty-pro-1.0",
        {"orchestration_roles": {"planner": {"temperature": 3.0}}},
    )
    assert valid is False


def test_merge_orchestration_roles_preserves_other_roles() -> None:
    merged = merge_orchestration_roles_override(
        {"orchestration_roles": {"planner": {"temperature": 0.2}}},
        {"finalizer": {"max_tokens": 1200}},
    )
    assert "planner" in merged["orchestration_roles"]
    assert "finalizer" in merged["orchestration_roles"]
    assert merged["orchestration_roles"]["planner"]["temperature"] == 0.2


def test_select_roles_skips_disabled_optional_roles() -> None:
    roles_cfg = {
        "planner": {"enabled": True},
        "researcher": {"enabled": False},
        "critic": {"enabled": False},
        "finalizer": {"enabled": True},
    }
    roles = select_roles_for_run(roles_cfg, complexity_score=10, complexity_threshold=2, max_internal_calls=4)
    assert roles == ["planner", "finalizer"]


def test_resolve_effective_role_config_uses_defaults_when_unset() -> None:
    profile = ModelProfile(
        display_name="Pro",
        description="test",
        strategy="quality",
        search_mode="auto",
        default_temperature=0.5,
        provider_chain=[ProviderTarget(provider="groq", model="llama-3.3-70b-versatile")],
        orchestration_roles={
            "planner": OrchestrationRoleConfig(
                provider_chain=[ProviderTarget(provider="openrouter", model="moonshotai/kimi-k2.6:free")]
            )
        },
    )
    resolved = resolve_effective_role_config(
        "planner",
        profile.orchestration_roles["planner"],
        profile,
        request_temperature=0.7,
        request_max_tokens=4096,
        global_timeout_seconds=30.0,
    )
    assert resolved.provider_chain[0].provider == "openrouter"
    assert resolved.temperature == 0.7
    assert resolved.max_tokens == DEFAULT_ROLE_MAX_TOKENS["planner"]
    assert resolved.timeout_seconds == 30.0


def test_resolve_effective_role_config_caps_max_tokens_to_request() -> None:
    profile = ModelProfile(
        display_name="Pro",
        description="test",
        strategy="quality",
        search_mode="auto",
        provider_chain=[ProviderTarget(provider="groq", model="llama-3.3-70b-versatile")],
    )
    resolved = resolve_effective_role_config(
        "finalizer",
        {"max_tokens": 4096},
        profile,
        request_temperature=0.5,
        request_max_tokens=300,
        global_timeout_seconds=30.0,
    )
    assert resolved.max_tokens == 300


@dataclass
class _RecordingRouteResult:
    provider_result: ProviderChatResult
    provider_used: str


class _RecordingRouter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_with_provider_chain(
        self,
        request_id,
        provider_chain,
        messages,
        temperature,
        max_tokens,
        trace_label="custom_chain",
    ):
        self.calls.append(
            {
                "trace_label": trace_label,
                "provider_chain": provider_chain,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "message_count": len(messages),
                "has_role_prompt_leak": any("planning role" in m.content for m in messages if hasattr(m, "content")),
            }
        )
        role_name = trace_label.split(":")[-1]
        return _RecordingRouteResult(
            provider_result=ProviderChatResult(
                provider=str(provider_chain[0].provider),
                content=f"{role_name} output",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
            provider_used=str(provider_chain[0].provider),
        )


@pytest.mark.asyncio
async def test_per_role_settings_used_in_execution() -> None:
    router = _RecordingRouter()
    orchestrator = NestyProMultiModelOrchestrator(router=router)
    profile = ModelProfile(
        display_name="Pro",
        description="test",
        strategy="quality",
        search_mode="auto",
        provider_chain=[ProviderTarget(provider="groq", model="fallback-model")],
        orchestration_roles={
            "planner": OrchestrationRoleConfig(
                provider_chain=[ProviderTarget(provider="groq", model="planner-model")],
                temperature=0.2,
                max_tokens=400,
                timeout_seconds=12.0,
            ),
            "finalizer": OrchestrationRoleConfig(
                provider_chain=[ProviderTarget(provider="openrouter", model="finalizer-model")],
                temperature=0.6,
                max_tokens=900,
            ),
        },
    )
    result = await orchestrator.run(
        request_id="req-role-settings",
        user_message="Analyze this architecture",
        prepared_messages=[],
        model_alias="nesty-pro-1.0",
        model_profile=profile,
        selected_roles=["planner", "finalizer"],
        temperature=0.9,
        max_tokens=4096,
        role_timeout_seconds=30.0,
        max_context_chars=4000,
        include_role_latency=False,
    )
    assert result.content == "finalizer output"
    assert len(router.calls) == 2
    assert router.calls[0]["temperature"] == 0.2
    assert router.calls[0]["max_tokens"] == 400
    assert router.calls[0]["provider_chain"][0].model == "planner-model"
    assert router.calls[1]["temperature"] == 0.6
    assert router.calls[1]["max_tokens"] == 900
    assert router.calls[1]["provider_chain"][0].provider == "openrouter"


def test_console_get_orchestration_config(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "orch_get.db")
    init_db(db_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: _console_settings(db_path))
    response = client.get(
        "/internal/console/runtime/model-configs/nesty-pro-1.0/orchestration",
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["model_id"] == "nesty-pro-1.0"
    assert body["supported_role_ids"] == ["planner", "researcher", "critic", "finalizer"]
    assert "planner" in body["effective_roles"]
    assert "planning role" not in str(body).lower()
    assert "orchestration" in body
    assert "roles" in body["orchestration"]


def test_console_patch_orchestration_roles(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "orch_patch.db")
    init_db(db_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: _console_settings(db_path))
    response = client.patch(
        "/internal/console/runtime/model-configs/nesty-pro-1.0/orchestration",
        headers=_admin_headers(),
        json={
            "roles": {
                "finalizer": {
                    "temperature": 0.35,
                    "max_tokens": 1500,
                    "provider_chain": [{"provider": "groq", "model": "llama-3.3-70b-versatile"}],
                }
            },
            "changed_by_label": "test",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["effective_roles"]["finalizer"]["temperature"] == 0.35
    assert body["effective_roles"]["finalizer"]["max_tokens"] == 1500


def test_console_patch_rejects_disabling_planner(client, monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "orch_patch_invalid.db")
    init_db(db_path)
    monkeypatch.setattr("app.deps.get_settings", lambda: _console_settings(db_path))
    response = client.patch(
        "/internal/console/runtime/model-configs/nesty-pro-1.0/orchestration",
        headers=_admin_headers(),
        json={"roles": {"planner": {"enabled": False}}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_config_invalid"


def test_required_role_disabled_blocks_orchestration_at_runtime() -> None:
    from types import SimpleNamespace

    request = SimpleNamespace(orchestration="force", stream=False)
    model_config = {
        "orchestration_enabled": True,
        "orchestration_mode": "multi_model_synthesis",
        "orchestration_roles": {
            "planner": {"enabled": False, "provider_chain": [{"provider": "groq", "model": "x"}]},
            "finalizer": {"provider_chain": [{"provider": "groq", "model": "y"}]},
        },
    }
    config = SimpleNamespace(
        nesty_pro_orchestration_enabled=True,
        nesty_pro_orchestration_max_internal_calls=4,
        nesty_pro_orchestration_complexity_min_score=2,
        nesty_pro_orchestration_simple_max_chars=220,
    )
    decision = should_use_orchestration(
        "nesty-pro-1.0",
        request,
        model_config,
        {"latest_user_message": "complex analyze debug architecture"},
        config,
    )
    assert decision["should_use"] is False
    assert decision["reason"] == "required_role_disabled"
