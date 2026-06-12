from __future__ import annotations

import os
import sqlite3
import yaml
from pathlib import Path
from typing import Any

from app.config import Settings, load_models_config
from app.core.runtime_providers.validation import get_supported_chat_provider_ids
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.storage.db import init_db


def _resolve_project_root(project_root: Path | None = None) -> Path:
    if project_root:
        return Path(project_root).resolve()
    return Path(__file__).resolve().parents[3]


def validate_required_files(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = _resolve_project_root(project_root)
    results = []

    # Check models.yaml
    models_path = root / "config" / "models.yaml"
    if not models_path.exists():
        results.append({
            "name": "models_config_file",
            "status": "FAIL",
            "message": f"config/models.yaml does not exist at {models_path}"
        })
    else:
        try:
            with models_path.open("r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
            if not content or "models" not in content:
                results.append({
                    "name": "models_config_file",
                    "status": "FAIL",
                    "message": "config/models.yaml is empty or missing 'models' root key"
                })
            else:
                results.append({
                    "name": "models_config_file",
                    "status": "PASS",
                    "message": "config/models.yaml exists and is valid YAML"
                })
        except Exception as e:
            results.append({
                "name": "models_config_file",
                "status": "FAIL",
                "message": f"Failed to parse config/models.yaml: {e}"
            })

    # Check guard_rules.yaml
    guard_path = root / "config" / "guard_rules.yaml"
    if not guard_path.exists():
        results.append({
            "name": "guard_rules_file",
            "status": "FAIL",
            "message": f"config/guard_rules.yaml does not exist at {guard_path}"
        })
    else:
        try:
            with guard_path.open("r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
            results.append({
                "name": "guard_rules_file",
                "status": "PASS",
                "message": "config/guard_rules.yaml exists and is valid YAML"
            })
        except Exception as e:
            results.append({
                "name": "guard_rules_file",
                "status": "FAIL",
                "message": f"Failed to parse config/guard_rules.yaml: {e}"
            })

    # Check .env or .env.example
    env_path = root / ".env"
    env_example_path = root / ".env.example"
    if env_path.exists():
        results.append({
            "name": "env_file",
            "status": "PASS",
            "message": ".env file is present"
        })
    elif env_example_path.exists():
        results.append({
            "name": "env_file",
            "status": "WARN",
            "message": ".env file is missing, but .env.example is present as a template"
        })
    else:
        results.append({
            "name": "env_file",
            "status": "FAIL",
            "message": "Both .env and .env.example are missing"
        })

    # Check docs/COMPATIBILITY.md
    compat_path = root / "docs" / "COMPATIBILITY.md"
    if compat_path.exists():
        results.append({
            "name": "compatibility_doc",
            "status": "PASS",
            "message": "docs/COMPATIBILITY.md is present"
        })
    else:
        results.append({
            "name": "compatibility_doc",
            "status": "WARN",
            "message": "docs/COMPATIBILITY.md is missing. Create it to document the public API compatibility contract."
        })

    return results



def validate_model_chains(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = _resolve_project_root(project_root)
    results = []
    models_path = root / "config" / "models.yaml"

    if not models_path.exists():
        results.append({
            "name": "model_chains",
            "status": "FAIL",
            "message": "Cannot validate model chains: config/models.yaml is missing"
        })
        return results

    try:
        models_config = load_models_config(models_path)
        embedding_keywords = {"embed", "similarity", "vector", "clip"}
        supported_providers = set(BUILTIN_PROVIDER_IDS)

        for model_id, profile in models_config.models.items():
            # Check main provider chain
            for idx, target in enumerate(profile.provider_chain):
                provider_name = str(target.provider or "").strip()
                if provider_name not in supported_providers:
                    results.append({
                        "name": f"model_chain_{model_id}_main_{idx}",
                        "status": "FAIL",
                        "message": f"Unsupported provider '{provider_name}' in chat provider chain for model alias '{model_id}'."
                    })
                model_name = target.model.lower()
                if any(kw in model_name for kw in embedding_keywords):
                    results.append({
                        "name": f"model_chain_{model_id}_main_{idx}",
                        "status": "FAIL",
                        "message": f"Embedding-like model '{target.model}' found in chat provider chain for model alias '{model_id}'."
                    })

            # Check orchestration roles
            for role_name, role_cfg in profile.orchestration_roles.items():
                for idx, target in enumerate(role_cfg.provider_chain):
                    provider_name = str(target.provider or "").strip()
                    if provider_name not in supported_providers:
                        results.append({
                            "name": f"model_chain_{model_id}_{role_name}_{idx}",
                            "status": "FAIL",
                            "message": f"Unsupported provider '{provider_name}' in orchestration role '{role_name}' for model alias '{model_id}'."
                        })
                    model_name = target.model.lower()
                    if any(kw in model_name for kw in embedding_keywords):
                        results.append({
                            "name": f"model_chain_{model_id}_{role_name}_{idx}",
                            "status": "FAIL",
                            "message": f"Embedding-like model '{target.model}' found in orchestration role '{role_name}' provider chain for model alias '{model_id}'."
                        })

        if not results:
            results.append({
                "name": "model_chains",
                "status": "PASS",
                "message": "All chat provider chains are clean of embedding-like models"
            })

    except Exception as e:
        results.append({
            "name": "model_chains",
            "status": "FAIL",
            "message": f"Error parsing/validating model chains: {e}"
        })

    return results


def validate_env_safety(settings: Settings | None = None) -> list[dict[str, Any]]:
    from app.deps import get_settings
    s = settings or get_settings()
    results = []

    # REQUIRE_API_KEY check
    if s.require_api_key:
        secret = s.nesty_api_key_hash_secret
        if not secret or secret in {
            "replace_with_a_strong_secret",
            "replace_with_strong_secret",
            "change-me-in-production-please-do-not-leave-default",
            "replace_me_with_a_long_random_string_or_secure_key"
        }:
            results.append({
                "name": "api_key_hash_secret",
                "status": "WARN",
                "message": "REQUIRE_API_KEY=true, but NESTY_API_KEY_HASH_SECRET is missing, empty, or using a default placeholder. Please set a strong secret in production."
            })
        else:
            results.append({
                "name": "api_key_hash_secret",
                "status": "PASS",
                "message": "NESTY_API_KEY_HASH_SECRET is configured"
            })
    else:
        results.append({
            "name": "api_key_hash_secret",
            "status": "PASS",
            "message": "REQUIRE_API_KEY=false (API key authorization is disabled)"
        })

    # INTERNAL_ADMIN_ENABLED check
    if s.internal_admin_enabled:
        token = s.nesty_internal_admin_token
        mode = str(getattr(s, "nesty_internal_admin_token_mode", "env") or "env").strip().lower()
        if token and len(token.strip()) >= 8:
            results.append({
                "name": "internal_admin_token",
                "status": "PASS",
                "message": "NESTY_INTERNAL_ADMIN_TOKEN is configured securely"
            })
        elif mode == "file":
            results.append({
                "name": "internal_admin_token",
                "status": "PASS",
                "message": "Internal admin token will be loaded or generated from file at startup (NESTY_INTERNAL_ADMIN_TOKEN_MODE=file)."
            })
        elif mode == "ephemeral":
            results.append({
                "name": "internal_admin_token",
                "status": "WARN",
                "message": "Ephemeral internal admin token mode is enabled. Token changes on restart; use env or file mode for personal self-host production."
            })
        else:
            results.append({
                "name": "internal_admin_token",
                "status": "WARN",
                "message": "INTERNAL_ADMIN_ENABLED=true, but NESTY_INTERNAL_ADMIN_TOKEN is missing or too short (must be at least 8 characters)."
            })
    else:
        results.append({
            "name": "internal_admin_token",
            "status": "PASS",
            "message": "INTERNAL_ADMIN_ENABLED=false (internal admin endpoints are disabled)"
        })

    # CORS wildcards in production
    if s.cors_enabled:
        origins = [item.strip() for item in s.cors_allow_origins.split(",") if item.strip()]
        is_production = s.app_env.strip().lower() == "production"
        if is_production and s.require_api_key and "*" in origins:
            results.append({
                "name": "cors_wildcard_production",
                "status": "FAIL",
                "message": "unsafe_cors_configuration: wildcard CORS ('*') is not allowed in production when REQUIRE_API_KEY=true."
            })
        elif is_production and "*" in origins:
            results.append({
                "name": "cors_wildcard_production",
                "status": "WARN",
                "message": "Wildcard CORS ('*') is enabled in production. This can expose endpoints to CSRF unless protected by authorization."
            })
        else:
            results.append({
                "name": "cors_wildcard_production",
                "status": "PASS",
                "message": "CORS configuration is safe"
            })
    else:
        results.append({
            "name": "cors_wildcard_production",
            "status": "PASS",
            "message": "CORS is disabled"
        })

    return results


def validate_runtime_setup(settings: Settings | None = None) -> list[dict[str, Any]]:
    from app.deps import get_settings
    s = settings or get_settings()
    results = []

    # SQLite DB check
    db_path = s.nesty_db_path
    try:
        init_db(db_path)
        results.append({
            "name": "sqlite_db_init",
            "status": "PASS",
            "message": f"SQLite database successfully initialized/verified at '{db_path}'"
        })
    except Exception as e:
        results.append({
            "name": "sqlite_db_init",
            "status": "FAIL",
            "message": f"Failed to initialize SQLite database at '{db_path}': {e}"
        })

    # FTS5 check
    try:
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE VIRTUAL TABLE fts_test USING fts5(content);")
        results.append({
            "name": "fts5_availability",
            "status": "PASS",
            "message": "SQLite FTS5 virtual table extension is available"
        })
    except Exception:
        results.append({
            "name": "fts5_availability",
            "status": "WARN",
            "message": "SQLite FTS5 extension is not available. Search fallback (LIKE-based) will be used."
        })

    # Provider API keys check
    provider_keys = {
        "GROQ_API_KEY": s.groq_api_key,
        "OPENROUTER_API_KEY": s.openrouter_api_key,
        "NVIDIA_API_KEY": s.nvidia_api_key,
        "OLLAMA_API_KEY": s.ollama_api_key,
    }

    set_keys = [k for k, v in provider_keys.items() if v and len(v.strip()) > 0]

    for k, v in provider_keys.items():
        is_set = v and len(v.strip()) > 0
        status_str = "set" if is_set else "missing"
        results.append({
            "name": f"env_var_{k.lower()}",
            "status": "PASS" if is_set else "WARN",
            "message": f"{k} is {status_str}"
        })

    if not set_keys:
        results.append({
            "name": "provider_api_keys",
            "status": "WARN",
            "message": "No provider API keys are configured (GROQ_API_KEY, OPENROUTER_API_KEY, NVIDIA_API_KEY, OLLAMA_API_KEY). At least one is required to route chat completions."
        })
    else:
        results.append({
            "name": "provider_api_keys",
            "status": "PASS",
            "message": f"Configured provider API keys: {', '.join(set_keys)}"
        })

    ollama_base_url = str(getattr(s, "ollama_base_url", "") or "").strip()
    if ollama_base_url and not (ollama_base_url.startswith("http://") or ollama_base_url.startswith("https://")):
        results.append(
            {
                "name": "ollama_base_url_shape",
                "status": "WARN",
                "message": "OLLAMA_BASE_URL should start with http:// or https://",
            }
        )
    else:
        results.append(
            {
                "name": "ollama_base_url_shape",
                "status": "PASS",
                "message": "OLLAMA_BASE_URL shape looks valid",
            }
        )

    return results
