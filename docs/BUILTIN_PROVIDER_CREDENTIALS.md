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

## Built-in provider endpoints (hardcoded)

Defaults live in `app/providers/constants.py`. For most built-ins you only configure the **API key** (env or Console managed secret). Base URL env vars are required only where noted.

| ID | Default endpoint | API key env | Base URL env |
|----|------------------|-------------|--------------|
| `openai` | `https://api.openai.com/v1/chat/completions` | `OPENAI_API_KEY` | — |
| `mistral` | `https://api.mistral.ai/v1/chat/completions` | `MISTRAL_API_KEY` | — |
| `deepseek` | `https://api.deepseek.com/v1/chat/completions` | `DEEPSEEK_API_KEY` | — |
| `z_ai` | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `Z_AI_API_KEY` | optional `Z_AI_BASE_URL` (e.g. GLM Coding Plan) |
| `google_gemini` | `https://generativelanguage.googleapis.com/v1beta` | `GOOGLE_GEMINI_API_KEY` | — |
| `anthropic_claude` | `https://api.anthropic.com/v1/messages` | `ANTHROPIC_API_KEY` | — |
| `groq` | `https://api.groq.com/openai/v1/chat/completions` | `GROQ_API_KEY` | — |
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions` | `OPENROUTER_API_KEY` | — |
| `ollama_cloud` | `https://ollama.com/api/chat` (default base) | `OLLAMA_API_KEY` | optional `OLLAMA_BASE_URL` |
| `nvidia` | *(from env)* | `NVIDIA_API_KEY` | **`NVIDIA_BASE_URL`** (required) |

## New built-in provider IDs

| ID | Type | Env key |
|----|------|---------|
| `openai` | OpenAI-compatible | `OPENAI_API_KEY` |
| `mistral` | OpenAI-compatible | `MISTRAL_API_KEY` |
| `z_ai` | OpenAI-compatible (Zhipu AI / 智谱) | `Z_AI_API_KEY` only (optional `Z_AI_BASE_URL` for Coding Plan) |
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
