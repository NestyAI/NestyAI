from __future__ import annotations

# Upstash REST credential backend is planned for a future release.
# v1.6.0 uses SQLite metadata + file-backed secrets only.
#
# When implemented, secrets would be stored encrypted in Upstash with refs
# persisted in provider_credentials.secret_ref. No new dependency is added
# in v1.6.0 unless explicitly approved.
