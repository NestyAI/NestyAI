from __future__ import annotations

from typing import Protocol

from app.core.provider_credentials.models import ProviderCredentialRecord


class CredentialStoreBackend(Protocol):
    def get(self, provider_id: str, credential_name: str = "api_key") -> ProviderCredentialRecord | None: ...

    def list(self, provider_id: str | None = None) -> list[ProviderCredentialRecord]: ...

    def upsert_managed(
        self,
        provider_id: str,
        api_key: str,
        *,
        credential_name: str = "api_key",
        rotated: bool = False,
    ) -> ProviderCredentialRecord: ...

    def delete(self, provider_id: str, credential_name: str = "api_key") -> bool: ...
