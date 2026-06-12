from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CredentialSource = Literal["managed_store", "secret_file", "env"]
SecretStatus = Literal["configured", "missing", "disabled", "env_ref", "stored", "managed", "none"]


@dataclass(frozen=True)
class ProviderCredentialRecord:
    provider_id: str
    credential_name: str
    source: CredentialSource
    secret_ref: str | None
    enabled: bool
    created_at: str
    updated_at: str
    last_rotated_at: str | None = None

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "credential_name": self.credential_name,
            "source": self.source,
            "secret_ref": self.secret_ref,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_rotated_at": self.last_rotated_at,
        }
