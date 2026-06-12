from __future__ import annotations

from typing import Any

from app.core.bootstrap.console_client_secret import resolve_console_client_secret
from app.core.bootstrap.internal_admin_token import resolve_internal_admin_token


def resolve_bootstrap_credentials(settings: Any) -> Any:
    admin_result = resolve_internal_admin_token(settings)
    console_result = resolve_console_client_secret(settings)

    updates: dict[str, Any] = {
        "nesty_internal_admin_token": admin_result.token,
        "internal_admin_token_source": admin_result.source,
        "internal_admin_token_file_resolved": admin_result.file_path,
        "nesty_console_client_secret": console_result.secret,
        "console_client_secret_source": console_result.source,
        "console_client_secret_file_resolved": console_result.file_path,
    }
    return settings.model_copy(update=updates)
