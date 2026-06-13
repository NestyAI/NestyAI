from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.core.bootstrap.secret_file import (
    generate_urlsafe_secret,
    read_secret_file,
    resolve_secret_file_path,
    write_secret_file,
)
from app.utils.logging import get_logger, log_safe


logger = get_logger("nesty.bootstrap.internal_admin_token")

_VALID_MODES = {"env", "file", "ephemeral"}


@dataclass(frozen=True)
class InternalAdminTokenBootstrapResult:
    token: str | None
    source: str
    file_path: str | None = None
    generated: bool = False


def _env_token(settings: Any) -> str | None:
    env_value = os.getenv("NESTY_INTERNAL_ADMIN_TOKEN")
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()
    configured = getattr(settings, "nesty_internal_admin_token", None)
    if configured is not None and str(configured).strip():
        return str(configured).strip()
    return None


def resolve_internal_admin_token(settings: Any) -> InternalAdminTokenBootstrapResult:
    env_value = os.getenv("NESTY_INTERNAL_ADMIN_TOKEN")
    if env_value is not None and str(env_value).strip():
        token = str(env_value).strip()
        log_safe(logger, "internal_admin_token_resolved", source="env", file_path=None, generated=False)
        return InternalAdminTokenBootstrapResult(token=token, source="env")

    enabled = bool(getattr(settings, "internal_admin_enabled", False))
    mode = str(getattr(settings, "nesty_internal_admin_token_mode", "env") or "env").strip().lower()
    if mode not in _VALID_MODES:
        mode = "env"

    if not enabled and mode == "env":
        return InternalAdminTokenBootstrapResult(token=_env_token(settings), source="env")

    if not enabled and mode in {"file", "ephemeral"}:
        log_safe(
            logger,
            "internal_admin_token_bootstrap_skipped",
            reason="internal_admin_disabled",
            mode=mode,
        )
        return InternalAdminTokenBootstrapResult(token=None, source="disabled")

    file_path = resolve_secret_file_path(
        str(getattr(settings, "internal_admin_token_file", ".nesty/internal_admin_token"))
    )
    print_flag = bool(getattr(settings, "nesty_print_bootstrap_admin_token", False))

    if mode == "env":
        token = _env_token(settings)
        log_safe(logger, "internal_admin_token_resolved", source="env", file_path=None, generated=False)
        return InternalAdminTokenBootstrapResult(token=token, source="env")

    if mode == "file":
        rotate_on_start = bool(getattr(settings, "nesty_internal_admin_token_rotate_on_start", False))
        existing = None if rotate_on_start else read_secret_file(file_path)
        if existing:
            log_safe(
                logger,
                "internal_admin_token_resolved",
                source="file",
                file_path=str(file_path),
                generated=False,
            )
            return InternalAdminTokenBootstrapResult(
                token=existing,
                source="file",
                file_path=str(file_path),
            )
        generated_token = generate_urlsafe_secret("nia")
        write_secret_file(file_path, generated_token)
        log_safe(
            logger,
            "internal_admin_token_resolved",
            source="file",
            file_path=str(file_path),
            generated=True,
        )
        if print_flag:
            logger.warning(
                "Generated internal admin token saved to %s. Token prints at startup when NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN=true.",
                file_path,
            )
        else:
            logger.warning(
                "Generated internal admin token and saved to %s. Set NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN=true to print once.",
                file_path,
            )
        return InternalAdminTokenBootstrapResult(
            token=generated_token,
            source="file",
            file_path=str(file_path),
            generated=True,
        )

    generated_token = generate_urlsafe_secret("nia")
    log_safe(logger, "internal_admin_token_resolved", source="ephemeral", file_path=None, generated=True)
    logger.warning(
        "Ephemeral internal admin token generated for this process only. "
        "It changes on restart; use env or file mode for personal self-host production."
    )
    if print_flag:
        logger.warning(
            "Ephemeral internal admin token ready. Token prints at startup when NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN=true."
        )
    return InternalAdminTokenBootstrapResult(
        token=generated_token,
        source="ephemeral",
        generated=True,
    )


def print_internal_admin_token_startup_banner(settings: Any) -> None:
    """Print internal admin token at Gateway startup (lifespan), next to ephemeral Console API key."""
    if not bool(getattr(settings, "nesty_print_bootstrap_admin_token", False)):
        return
    if not bool(getattr(settings, "internal_admin_enabled", False)):
        logger.warning(
            "NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN=true but INTERNAL_ADMIN_ENABLED=false; "
            "internal admin token banner skipped."
        )
        return

    token = getattr(settings, "nesty_internal_admin_token", None)
    if token is None or not str(token).strip():
        logger.warning(
            "NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN=true but no internal admin token is configured. "
            "Use NESTY_INTERNAL_ADMIN_TOKEN_MODE=ephemeral (or file) and leave NESTY_INTERNAL_ADMIN_TOKEN unset."
        )
        return

    mode = str(getattr(settings, "nesty_internal_admin_token_mode", "env") or "env").strip().lower()
    env_override = os.getenv("NESTY_INTERNAL_ADMIN_TOKEN")
    if mode == "env" and env_override is not None and str(env_override).strip():
        return

    print("=" * 88, flush=True)
    print(
        "EPHEMERAL NESTY INTERNAL ADMIN TOKEN - copy into Nesty Console "
        "(NESTY_INTERNAL_ADMIN_TOKEN). Rotates on restart when MODE=ephemeral.",
        flush=True,
    )
    print(str(token).strip(), flush=True)
    print("=" * 88, flush=True)


def admin_token_status(settings: Any) -> dict[str, str | bool | None]:
    mode = str(getattr(settings, "nesty_internal_admin_token_mode", "env") or "env").strip().lower()
    source = str(getattr(settings, "internal_admin_token_source", None) or mode)
    file_path = getattr(settings, "internal_admin_token_file_resolved", None)
    configured = bool(getattr(settings, "nesty_internal_admin_token", None))
    return {
        "mode": mode,
        "source": source,
        "configured": configured,
        "file_path": str(file_path) if file_path else None,
        "rotate_on_start": bool(getattr(settings, "nesty_internal_admin_token_rotate_on_start", False)),
        "rotation_supported": mode == "file",
    }


def rotate_file_backed_admin_token(settings: Any) -> InternalAdminTokenBootstrapResult:
    mode = str(getattr(settings, "nesty_internal_admin_token_mode", "env") or "env").strip().lower()
    if mode == "env":
        raise ValueError("admin_token_rotation_unsupported_env")
    if mode == "ephemeral":
        raise ValueError("admin_token_rotation_unsupported_ephemeral")
    if mode != "file":
        raise ValueError("admin_token_rotation_unsupported")
    if not bool(getattr(settings, "internal_admin_enabled", False)):
        raise ValueError("internal_admin_disabled")

    file_path = resolve_secret_file_path(
        str(getattr(settings, "internal_admin_token_file", ".nesty/internal_admin_token"))
    )
    generated_token = generate_urlsafe_secret("nia")
    write_secret_file(file_path, generated_token)
    print_flag = bool(getattr(settings, "nesty_print_bootstrap_admin_token", False))
    log_safe(
        logger,
        "internal_admin_token_rotated",
        source="file",
        file_path=str(file_path),
        generated=True,
    )
    if print_flag:
        print(f"NESTY_INTERNAL_ADMIN_TOKEN={generated_token}")
    else:
        logger.warning(
            "Internal admin token rotated and saved to %s. Token is not included in API responses.",
            file_path,
        )
    return InternalAdminTokenBootstrapResult(
        token=generated_token,
        source="file",
        file_path=str(file_path),
        generated=True,
    )
