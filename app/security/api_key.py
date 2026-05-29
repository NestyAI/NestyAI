from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_api_key(environment: str = "dev") -> str:
    env = "live" if environment.strip().lower() == "live" else "dev"
    token = secrets.token_urlsafe(32)
    return f"nsk_{env}_{token}"


def hash_api_key(api_key: str, hash_secret: str | None = None) -> str:
    data = api_key.encode("utf-8")
    if hash_secret:
        digest = hmac.new(hash_secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
        return f"hmac_sha256:{digest}"
    digest = hashlib.sha256(data).hexdigest()
    return f"sha256:{digest}"


def verify_api_key(raw_key: str, stored_hash: str, hash_secret: str | None = None) -> bool:
    expected = hash_api_key(raw_key, hash_secret=hash_secret)
    return hmac.compare_digest(expected, stored_hash)


def get_key_prefix(raw_key: str) -> str:
    return raw_key[:12]

