# Built-in Provider Credentials (v1.6.0)

Gateway-only credential management for **built-in** providers. Runtime OpenAI-compatible providers continue to use `/internal/console/runtime/providers/*`.

## Default behavior (unchanged)

`NESTY_PROVIDER_CREDENTIALS_ENABLED=false` (default). Existing env-based provider keys behave exactly as in v1.5.x.

## When enabled

Set `NESTY_PROVIDER_CREDENTIALS_ENABLED=true`. Resolution priority (configurable):

```
NESTY_PROVIDER_CREDENTIAL_SOURCE_PRIORITY=managed,secret_file,env
```

1. **managed_store** — SQLite metadata + secret file at `.nesty/provider_secrets/builtin/{provider_id}.secret`
2. **secret_file** — same directory without a managed row
3. **env** — existing `Settings` / env vars (e.g. `OPENAI_API_KEY`)
4. **missing** — provider registered; requests fail at call time with `MissingAPIKeyError`

Managed credentials override env **only when explicitly configured** for that provider.

## Storage

| Layer | Contents |
|-------|----------|
| SQLite `provider_credentials` | metadata only (`source`, `secret_ref`, timestamps) |
| `.nesty/provider_secrets/builtin/` | actual API key bytes (`0o600` files) |

Never store raw API keys in SQLite.

## Internal APIs

Prefix: `/internal/console/runtime` (requires Internal Admin Token + optional console client auth)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/builtin-providers` | List built-in capabilities + credential status |
| GET | `/builtin-providers/{id}` | Single built-in detail |
| GET | `/builtin-providers/{id}/credentials` | Safe credential metadata |
| PUT | `/builtin-providers/{id}/credentials/api-key` | Store managed credential |
| DELETE | `/builtin-providers/{id}/credentials/api-key` | Remove managed credential |
| POST | `/builtin-providers/{id}/credentials/api-key/test` | Probe provider |
| POST | `/builtin-providers/{id}/credentials/api-key/rotate` | Rotate managed secret |

Built-in provider **definitions** are immutable via API (no delete/rename).

## New built-in provider IDs

| ID | Type | Env key |
|----|------|---------|
| `openai` | OpenAI-compatible | `OPENAI_API_KEY` |
| `mistral` | OpenAI-compatible | `MISTRAL_API_KEY` |
| `z_ai` | OpenAI-compatible | `Z_AI_API_KEY` / `Z_AI_BASE_URL` |
| `google_gemini` | Native | `GOOGLE_GEMINI_API_KEY` |
| `anthropic_claude` | Native | `ANTHROPIC_API_KEY` |

Default `config/models.yaml` chains are **not** modified in v1.6.0. Add new provider IDs to model overrides when ready.

## Admin token lifecycle

See `/internal/console/security/admin-token/status` and `/rotate`.

- **env** mode: rotation unsupported via API (update env manually)
- **file** mode: rotation writes a new token to `INTERNAL_ADMIN_TOKEN_FILE`
- `NESTY_INTERNAL_ADMIN_TOKEN_ROTATE_ON_START=false` by default
- `NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN=false` by default (no token printed on boot)

## Future: Upstash

`NESTY_PROVIDER_CREDENTIAL_STORE=upstash` and Upstash REST env vars are reserved for a future release. v1.6.0 uses SQLite + file-backed secrets only.
