from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.config import get_project_root
from app.core.bootstrap.secret_file import write_secret_file


def resolve_secret_dir(settings: Any) -> Path:
    raw = str(getattr(settings, "nesty_runtime_provider_secret_dir", ".nesty/provider_secrets") or ".nesty/provider_secrets")
    path = Path(raw)
    if path.is_absolute():
        return path
    return get_project_root() / path


def secret_ref_for_provider(provider_id: str) -> str:
    return f"{provider_id}.secret"


def secret_file_path(settings: Any, provider_id: str) -> Path:
    return resolve_secret_dir(settings) / secret_ref_for_provider(provider_id)


def write_provider_secret(settings: Any, provider_id: str, api_key: str) -> str:
    path = secret_file_path(settings, provider_id)
    write_secret_file(path, api_key.strip())
    return secret_ref_for_provider(provider_id)


def read_provider_secret(settings: Any, provider_id: str, secret_ref: str | None) -> str | None:
    if not secret_ref:
        return None
    path = resolve_secret_dir(settings) / secret_ref
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def delete_provider_secret_file(settings: Any, provider_id: str, secret_ref: str | None) -> None:
    ref = secret_ref or secret_ref_for_provider(provider_id)
    path = resolve_secret_dir(settings) / ref
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def resolve_runtime_provider_api_key(
    *,
    settings: Any,
    provider_id: str,
    api_key_mode: str,
    api_key_env_name: str | None,
    api_key_secret_ref: str | None,
) -> tuple[str | None, str]:
    mode = str(api_key_mode or "none").strip().lower()
    if mode == "none":
        return None, "none"
    if mode == "env":
        env_name = str(api_key_env_name or "").strip()
        if not env_name:
            return None, "missing"
        value = os.getenv(env_name)
        if value is not None and str(value).strip():
            return str(value).strip(), "env_ref"
        return None, "missing"
    if mode == "secret_file":
        value = read_provider_secret(settings, provider_id, api_key_secret_ref)
        if value:
            return value, "stored"
        return None, "missing"
    return None, "missing"
