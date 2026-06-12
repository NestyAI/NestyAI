from __future__ import annotations

from typing import Any

from app.core.provider_credentials.models import ProviderCredentialRecord
from app.core.provider_credentials.secrets import write_builtin_provider_secret
from app.core.provider_credentials.store import (
    delete_provider_credential,
    get_provider_credential,
    list_provider_credentials,
    upsert_provider_credential,
)


class SQLiteFileCredentialBackend:
    """Default v1.6.0 backend: SQLite metadata + file-backed secrets."""

    def __init__(self, settings: Any, db_path: str | None = None) -> None:
        self.settings = settings
        self.db_path = db_path

    def get(self, provider_id: str, credential_name: str = "api_key") -> ProviderCredentialRecord | None:
        return get_provider_credential(
            provider_id,
            credential_name=credential_name,
            db_path=self.db_path,
            settings=self.settings,
        )

    def list(self, provider_id: str | None = None) -> list[ProviderCredentialRecord]:
        return list_provider_credentials(provider_id, db_path=self.db_path, settings=self.settings)

    def upsert_managed(
        self,
        provider_id: str,
        api_key: str,
        *,
        credential_name: str = "api_key",
        rotated: bool = False,
    ) -> ProviderCredentialRecord:
        secret_ref = write_builtin_provider_secret(self.settings, provider_id, api_key)
        return upsert_provider_credential(
            provider_id=provider_id,
            source="managed_store",
            secret_ref=secret_ref,
            credential_name=credential_name,
            enabled=True,
            rotated=rotated,
            db_path=self.db_path,
            settings=self.settings,
        )

    def delete(self, provider_id: str, credential_name: str = "api_key") -> bool:
        return delete_provider_credential(
            provider_id,
            credential_name=credential_name,
            db_path=self.db_path,
            settings=self.settings,
        )
