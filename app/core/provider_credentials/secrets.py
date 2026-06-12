from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_project_root
from app.core.bootstrap.secret_file import write_secret_file


BUILTIN_SECRET_SUBDIR = "builtin"


def resolve_provider_secret_root(settings: Any) -> Path:
    raw = str(getattr(settings, "nesty_provider_secret_dir", ".nesty/provider_secrets") or ".nesty/provider_secrets")
    path = Path(raw)
    if path.is_absolute():
        return path
    return get_project_root() / path


def resolve_builtin_secret_dir(settings: Any) -> Path:
    return resolve_provider_secret_root(settings) / BUILTIN_SECRET_SUBDIR


def secret_ref_for_provider(provider_id: str) -> str:
    return f"{BUILTIN_SECRET_SUBDIR}/{provider_id}.secret"


def secret_file_path(settings: Any, provider_id: str) -> Path:
    return resolve_builtin_secret_dir(settings) / f"{provider_id}.secret"


def write_builtin_provider_secret(settings: Any, provider_id: str, api_key: str) -> str:
    path = secret_file_path(settings, provider_id)
    write_secret_file(path, api_key.strip())
    return secret_ref_for_provider(provider_id)


def read_builtin_provider_secret(settings: Any, provider_id: str, secret_ref: str | None = None) -> str | None:
    ref = secret_ref or secret_ref_for_provider(provider_id)
    root = resolve_provider_secret_root(settings)
    path = root / ref
    if not path.is_file():
        alt = resolve_builtin_secret_dir(settings) / f"{provider_id}.secret"
        if alt.is_file():
            path = alt
        else:
            return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def delete_builtin_provider_secret(settings: Any, provider_id: str, secret_ref: str | None = None) -> None:
    ref = secret_ref or secret_ref_for_provider(provider_id)
    root = resolve_provider_secret_root(settings)
    path = root / ref
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass
    alt = secret_file_path(settings, provider_id)
    try:
        if alt.is_file():
            alt.unlink()
    except OSError:
        pass
