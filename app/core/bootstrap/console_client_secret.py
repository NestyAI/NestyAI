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


logger = get_logger("nesty.bootstrap.console_client_secret")

_VALID_MODES = {"env", "file", "ephemeral"}


@dataclass(frozen=True)
class ConsoleClientSecretBootstrapResult:
    secret: str | None
    source: str
    file_path: str | None = None
    generated: bool = False


def resolve_console_client_secret(settings: Any) -> ConsoleClientSecretBootstrapResult:
    auth_required = bool(getattr(settings, "nesty_console_client_auth_required", False))
    mode = str(getattr(settings, "nesty_console_client_secret_mode", "env") or "env").strip().lower()
    if mode not in _VALID_MODES:
        mode = "env"

    env_value = os.getenv("NESTY_CONSOLE_CLIENT_SECRET")
    if env_value is not None and str(env_value).strip():
        secret = str(env_value).strip()
        log_safe(logger, "console_client_secret_resolved", source="env", file_path=None, generated=False)
        return ConsoleClientSecretBootstrapResult(secret=secret, source="env")

    configured = getattr(settings, "nesty_console_client_secret", None)
    if configured is not None and str(configured).strip():
        secret = str(configured).strip()
        log_safe(logger, "console_client_secret_resolved", source="env", file_path=None, generated=False)
        return ConsoleClientSecretBootstrapResult(secret=secret, source="env")

    if not auth_required and mode == "env":
        return ConsoleClientSecretBootstrapResult(secret=None, source="env")

    if not auth_required and mode in {"file", "ephemeral"}:
        log_safe(
            logger,
            "console_client_secret_bootstrap_skipped",
            reason="console_client_auth_disabled",
            mode=mode,
        )
        return ConsoleClientSecretBootstrapResult(secret=None, source="disabled")

    file_path = resolve_secret_file_path(
        str(getattr(settings, "nesty_console_client_secret_file", ".nesty/console_client_secret"))
    )
    print_flag = bool(getattr(settings, "nesty_print_bootstrap_console_secret", False))

    if mode == "file":
        existing = read_secret_file(file_path)
        if existing:
            log_safe(
                logger,
                "console_client_secret_resolved",
                source="file",
                file_path=str(file_path),
                generated=False,
            )
            return ConsoleClientSecretBootstrapResult(
                secret=existing,
                source="file",
                file_path=str(file_path),
            )
        generated_secret = generate_urlsafe_secret("ncc")
        write_secret_file(file_path, generated_secret)
        log_safe(
            logger,
            "console_client_secret_resolved",
            source="file",
            file_path=str(file_path),
            generated=True,
        )
        if print_flag:
            print(f"NESTY_CONSOLE_CLIENT_SECRET={generated_secret}")
        else:
            logger.warning(
                "Generated console client secret saved to %s. Set NESTY_PRINT_BOOTSTRAP_CONSOLE_SECRET=true to print once.",
                file_path,
            )
        return ConsoleClientSecretBootstrapResult(
            secret=generated_secret,
            source="file",
            file_path=str(file_path),
            generated=True,
        )

    generated_secret = generate_urlsafe_secret("ncc")
    log_safe(logger, "console_client_secret_resolved", source="ephemeral", file_path=None, generated=True)
    logger.warning(
        "Ephemeral console client secret generated for this process only. "
        "It changes on restart; use env or file mode for personal self-host production."
    )
    if print_flag:
        print(f"NESTY_CONSOLE_CLIENT_SECRET={generated_secret}")
    return ConsoleClientSecretBootstrapResult(
        secret=generated_secret,
        source="ephemeral",
        generated=True,
    )
