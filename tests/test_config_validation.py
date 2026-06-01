from __future__ import annotations

import os
import yaml
from pathlib import Path
import pytest
from app.config import Settings
from app.core.config_validation import (
    validate_required_files,
    validate_model_chains,
    validate_env_safety,
    validate_runtime_setup,
)


def test_validate_required_files_missing(tmp_path: Path) -> None:
    # Test all missing
    results = validate_required_files(tmp_path)
    res_map = {r["name"]: r for r in results}

    assert res_map["models_config_file"]["status"] == "FAIL"
    assert res_map["guard_rules_file"]["status"] == "FAIL"
    assert res_map["env_file"]["status"] == "FAIL"


def test_validate_required_files_present(tmp_path: Path) -> None:
    # Prepare files
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    models_file = config_dir / "models.yaml"
    models_file.write_text("models: {}", encoding="utf-8")

    guard_file = config_dir / "guard_rules.yaml"
    guard_file.write_text("rules: {}", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text("TEST=1", encoding="utf-8")

    results = validate_required_files(tmp_path)
    res_map = {r["name"]: r for r in results}

    assert res_map["models_config_file"]["status"] == "PASS"
    assert res_map["guard_rules_file"]["status"] == "PASS"
    assert res_map["env_file"]["status"] == "PASS"


def test_validate_required_files_invalid_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    models_file = config_dir / "models.yaml"
    models_file.write_text("models: {invalid yaml", encoding="utf-8")

    results = validate_required_files(tmp_path)
    res_map = {r["name"]: r for r in results}
    assert res_map["models_config_file"]["status"] == "FAIL"


def test_validate_model_chains_rejects_embedding(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Bad config containing 'embed' in chat chain
    bad_config = {
        "models": {
            "nesty-flash-1.0": {
                "display_name": "Flash",
                "description": "Flash",
                "strategy": "speed",
                "search_mode": "auto",
                "provider_chain": [
                    {"provider": "groq", "model": "llama-3-embed-model"}
                ]
            }
        }
    }

    models_file = config_dir / "models.yaml"
    models_file.write_text(yaml.dump(bad_config), encoding="utf-8")

    results = validate_model_chains(tmp_path)
    # Filter for failures
    failures = [r for r in results if r["status"] == "FAIL"]
    assert len(failures) == 1
    assert "Embedding-like model" in failures[0]["message"]


def test_validate_model_chains_clean(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    good_config = {
        "models": {
            "nesty-flash-1.0": {
                "display_name": "Flash",
                "description": "Flash",
                "strategy": "speed",
                "search_mode": "auto",
                "provider_chain": [
                    {"provider": "groq", "model": "llama-3-8b-instant"}
                ]
            }
        }
    }

    models_file = config_dir / "models.yaml"
    models_file.write_text(yaml.dump(good_config), encoding="utf-8")

    results = validate_model_chains(tmp_path)
    failures = [r for r in results if r["status"] == "FAIL"]
    assert len(failures) == 0


def test_validate_model_chains_rejects_unknown_provider(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    bad_config = {
        "models": {
            "nesty-flash-1.0": {
                "display_name": "Flash",
                "description": "Flash",
                "strategy": "speed",
                "search_mode": "auto",
                "provider_chain": [{"provider": "unknown", "model": "x"}],
            }
        }
    }
    models_file = config_dir / "models.yaml"
    models_file.write_text(yaml.dump(bad_config), encoding="utf-8")
    results = validate_model_chains(tmp_path)
    failures = [r for r in results if r["status"] == "FAIL"]
    assert failures
    assert "Unsupported provider" in failures[0]["message"]


def test_validate_env_safety_wildcard_cors_production() -> None:
    settings = Settings(
        app_env="production",
        require_api_key=True,
        cors_enabled=True,
        cors_allow_origins="*",
    )

    results = validate_env_safety(settings)
    failures = [r for r in results if r["status"] == "FAIL"]
    assert len(failures) == 1
    assert "unsafe_cors_configuration" in failures[0]["message"]


def test_validate_env_safety_insecure_secrets() -> None:
    settings = Settings(
        require_api_key=True,
        nesty_api_key_hash_secret="replace_with_strong_secret",
        internal_admin_enabled=True,
        nesty_internal_admin_token="",
    )

    results = validate_env_safety(settings)
    warnings = {r["name"]: r for r in results if r["status"] == "WARN"}
    assert "api_key_hash_secret" in warnings
    assert "internal_admin_token" in warnings


def test_validate_runtime_setup_missing_provider_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    settings = Settings(
        nesty_db_path=str(db_path),
        groq_api_key="",
        openrouter_api_key="",
        nvidia_api_key="",
    )

    results = validate_runtime_setup(settings)
    res_map = {r["name"]: r for r in results}

    assert res_map["sqlite_db_init"]["status"] == "PASS"
    assert res_map["provider_api_keys"]["status"] == "WARN"
    assert "No provider API keys are configured" in res_map["provider_api_keys"]["message"]


def test_validate_runtime_setup_with_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    settings = Settings(
        nesty_db_path=str(db_path),
        groq_api_key="gkey",
        openrouter_api_key="okey",
        nvidia_api_key="",
    )

    results = validate_runtime_setup(settings)
    res_map = {r["name"]: r for r in results}

    assert res_map["provider_api_keys"]["status"] == "PASS"
    assert "groq_api_key" in res_map["env_var_groq_api_key"]["name"]
    assert res_map["env_var_groq_api_key"]["status"] == "PASS"
    assert res_map["env_var_nvidia_api_key"]["status"] == "WARN"


def test_env_example_contains_cloudflare_tunnel_preset_vars() -> None:
    env_text = Path(".env.example").read_text(encoding="utf-8")
    required_lines = [
        "CLOUDFLARE_TUNNEL_TOKEN=",
        "CLOUDFLARE_TUNNEL_ENABLED=false",
        "TUNNEL_AUTO_INSTALL_CLOUDFLARED=1",
        "CLOUDFLARED_BIN_PATH=/home/container/.cloudflared/bin/cloudflared",
        "TUNNEL_ENABLED=1",
        "CLOUDFLARED_LOG_PATH=./cloudflare/cloudflared.log",
        "CLOUDFLARED_PID_PATH=./cloudflare/cloudflared.pid",
    ]
    for line in required_lines:
        assert line in env_text


def test_env_example_contains_ollama_cloud_vars() -> None:
    env_text = Path(".env.example").read_text(encoding="utf-8")
    assert "OLLAMA_API_KEY=" in env_text
    assert "OLLAMA_BASE_URL=https://ollama.com" in env_text
    assert "OLLAMA_REQUEST_TIMEOUT_SECONDS=60" in env_text


def test_deployment_doc_mentions_cloudflare_tunnel_modes() -> None:
    deployment_doc = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "Cloudflare Tunnel Deployment" in deployment_doc
    assert "Mode A: Docker Compose sidecar" in deployment_doc
    assert "Mode B: Pterodactyl / container-panel mode" in deployment_doc


def test_gitignore_protects_ai_and_cloudflared_runtime() -> None:
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    assert "AI.md" in ignored
    assert ".cloudflared/" in ignored
    assert "cloudflare/.log" in ignored
    assert "cloudflare/.pid" in ignored


def test_validate_runtime_setup_does_not_require_cloudflare_tunnel_token(tmp_path: Path) -> None:
    settings = Settings(
        nesty_db_path=str(tmp_path / "test_tunnel_optional.db"),
        groq_api_key="",
        openrouter_api_key="",
        nvidia_api_key="",
    )
    results = validate_runtime_setup(settings)
    failures = [item for item in results if item["status"] == "FAIL"]
    assert not failures


def test_validate_runtime_setup_invalid_ollama_base_url_warns(tmp_path: Path) -> None:
    settings = Settings(
        nesty_db_path=str(tmp_path / "test_ollama_url.db"),
        ollama_base_url="ollama.com",
    )
    results = validate_runtime_setup(settings)
    res_map = {r["name"]: r for r in results}
    assert res_map["ollama_base_url_shape"]["status"] == "WARN"
