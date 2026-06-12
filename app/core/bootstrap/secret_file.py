from __future__ import annotations

import os
import secrets
from pathlib import Path

from app.config import get_project_root


def resolve_secret_file_path(raw_path: str) -> Path:
    path = Path(raw_path.strip() or ".nesty/secret")
    if path.is_absolute():
        return path
    return get_project_root() / path


def read_secret_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def write_secret_file(path: Path, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass


def generate_urlsafe_secret(prefix: str) -> str:
    normalized_prefix = prefix.strip().rstrip("_")
    token = secrets.token_urlsafe(32)
    if normalized_prefix:
        return f"{normalized_prefix}_{token}"
    return token
