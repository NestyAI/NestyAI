# Runtime Config & Console Integration

NestyAI Gateway v1.5.0+ adds secure runtime configuration APIs for personal self-host operators and third-party/custom consoles. **v1.5.1** adds dynamic OpenAI-compatible provider registration.

> **Panel git sync vs token bootstrap:** Pterodactyl **git sync** (`bootstrap.py`, `git_sync.py`, `NESTY_BOOTSTRAP_GIT_SYNC`) resets tracked repo files to `origin/main` before Gateway starts. It is unrelated to Internal Admin Token / Console secret bootstrap below. See [DEPLOYMENT.md — Mode B](DEPLOYMENT.md).

## Design principles

- **Personal self-host first**: simple defaults, no multi-tenant registry, no billing/team features.
- **Additive APIs**: legacy `/internal/*` routes remain unchanged.
- **No runtime secret mutation**: provider API keys and env secrets cannot be changed via API.
- **Safe responses**: changed field names only; no admin tokens, console secrets, or provider keys in responses.

## Internal Admin Token bootstrap

| Mode | Env var | Behavior |
|------|---------|----------|
| `env` (default) | `NESTY_INTERNAL_ADMIN_TOKEN` | Use env token. Required when `INTERNAL_ADMIN_ENABLED=true` unless file/ephemeral mode is set. |
| `file` | `NESTY_INTERNAL_ADMIN_TOKEN_MODE=file` | If env token unset, load or generate `nia_*` token in `INTERNAL_ADMIN_TOKEN_FILE` (default `.nesty/internal_admin_token`). Recommended for personal self-host. |
| `ephemeral` | `NESTY_INTERNAL_ADMIN_TOKEN_MODE=ephemeral` | Generate `nia_*` at startup. Dev/local only; changes on restart. |

Rules:
- If `NESTY_INTERNAL_ADMIN_TOKEN` is set, it **always wins**.
- Tokens are never returned from any API.
- Print bootstrap token only when `NESTY_PRINT_BOOTSTRAP_ADMIN_TOKEN=true`.
- Bootstrap runs only when `INTERNAL_ADMIN_ENABLED=true` (or explicit file/ephemeral mode with admin enabled).

## Console Client auth (optional)

Disabled by default: `NESTY_CONSOLE_CLIENT_AUTH_REQUIRED=false`.

When enabled, `/internal/console/runtime/*` routes require:

```http
Authorization: Bearer <internal_admin_token>
X-Nesty-Console-ID: default-console
X-Nesty-Console-Secret: <console_secret>
```

Console secret bootstrap modes mirror admin token (`env`, `file`, `ephemeral`). Legacy `/internal/model-configs` and other `/internal/*` routes require Internal Admin Token only.

## Runtime config areas

| Area | API | Notes |
|------|-----|-------|
| Model overrides | `POST .../model-configs/{model_id}` | Same allowed fields as PATCH `/internal/model-configs/{model_id}` |
| Provider chain | `POST .../provider-chain/{model_id}` | Updates `provider_chain` only |
| Built-in provider routing disable | `POST .../providers/{id}/disable` | Routing-only skip; reversible (`runtime_gateway_state`) |
| Runtime provider CRUD | `POST .../providers/openai-compatible`, `GET/PATCH/DELETE .../providers/{id}` | OpenAI-compatible runtime providers only |
| Runtime provider test | `POST .../providers/{id}/test` | Live connectivity test with SSRF-safe URL checks |
| Validate | `POST .../validate` | Dry-run; no apply |
| Reload | `POST .../reload` | Clears runtime caches |
| Orchestration roles (v1.6.2) | `GET/PATCH .../model-configs/{model_id}/orchestration` | Safe ROLE-row config for Pro (`planner`, `researcher`, `critic`, `finalizer`) |

## Pro orchestration role config (v1.6.2)

Supported on `nesty-pro-1.0` via flat `orchestration_roles` (unchanged storage shape):

| Role | Required | Notes |
|------|----------|-------|
| `planner` | yes | Cannot be disabled |
| `researcher` | no | Optional; skipped when disabled |
| `critic` | no | Optional; skipped when disabled |
| `finalizer` | yes | Cannot be disabled |

Per-role fields: `enabled`, `provider_chain`, `temperature`, `max_tokens`, `timeout_seconds`.

Console GET returns nested view `orchestration.roles` for UI convenience; YAML/runtime storage remains `orchestration_roles`.

Role prompts and intermediate answers are never exposed via internal APIs.

Example PATCH body:

```json
{
  "roles": {
    "finalizer": {
      "temperature": 0.4,
      "max_tokens": 1600,
      "provider_chain": [{"provider": "groq", "model": "llama-3.3-70b-versatile"}]
    }
  }
}
```

## Provider expansion (v1.5.0)

Supported chat providers: `groq`, `openrouter`, `nvidia`, `ollama_cloud`, `deepseek`.

DeepSeek is opt-in:
1. Set `DEEPSEEK_API_KEY` in env.
2. Add `deepseek` to a model's `provider_chain` via runtime override or `config/models.yaml`.

DeepSeek is **not** in default model chains.

## Dynamic OpenAI-compatible providers (v1.5.1)

Runtime providers are **OpenAI-compatible only**. Non-OpenAI-compatible upstreams (custom auth schemes, proprietary APIs) require a built-in adapter in Gateway code — they cannot be registered dynamically.

### Feature flag

| Env var | Default | Behavior |
|---------|---------|----------|
| `NESTY_RUNTIME_OPENAI_PROVIDERS_ENABLED` | `true` | When `false`, runtime providers are not loaded for routing; provider-chain validation rejects runtime IDs; CRUD may still be used for preconfiguration; test returns `runtime_providers_disabled`. |

### Enable / disable semantics

| Provider kind | Disable API | Semantics |
|---------------|-------------|-----------|
| Built-in (`groq`, `openrouter`, …) | `POST .../providers/{id}/disable` | Routing-only disable in `runtime_gateway_state` (reversible) |
| Runtime (`custom_*`) | `POST .../providers/{id}/disable` | Persistent `enabled=false` in `runtime_provider_definitions` |

### Secret lifecycle (`api_key_mode=secret_file`)

- Create/update writes `.nesty/provider_secrets/{provider_id}.secret` with restrictive permissions where supported.
- Update with a new `api_key` rotates the secret file safely.
- Delete removes the provider secret file when owned by that provider.
- SQLite stores only `api_key_secret_ref`; responses, audit logs, and lifecycle metadata never include raw keys or file contents.

### Base URL safety (SSRF)

By default, runtime provider `base_url` values **reject**:

- `localhost`, `127.0.0.0/8`, `::1`
- Private RFC1918 ranges, link-local ranges
- Cloud metadata IPs such as `169.254.169.254`

The test endpoint applies the same checks and blocks DNS-resolved private/link-local/metadata targets unless dev flags allow them:

| Env var | Purpose |
|---------|---------|
| `NESTY_RUNTIME_PROVIDER_ALLOW_PRIVATE_BASE_URL` | Allow local/private hostnames and IPs (self-host/dev only — can be dangerous) |
| `NESTY_RUNTIME_PROVIDER_ALLOW_HTTP` | Allow non-HTTPS base URLs (dev/local only) |

### Header safety

`default_headers` must not include `Authorization`, `Cookie`, `X-Api-Key`, or other secret-like keys/values. Use `api_key_mode` instead.

### Example: register a runtime provider

```bash
curl -sS -X POST "http://127.0.0.1:8000/internal/console/runtime/providers/openai-compatible" \
  -H "Authorization: Bearer $NESTY_INTERNAL_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "custom_together",
    "display_name": "Together (OpenAI-compatible)",
    "base_url": "https://api.together.xyz",
    "api_key_mode": "secret_file",
    "api_key": "YOUR_UPSTREAM_KEY"
  }'
```

Then add `"custom_together"` to a model `provider_chain` via `POST .../provider-chain/{model_id}`.

## Security warnings

- Anyone with the Internal Admin Token can manage runtime config and API keys.
- Store bootstrap files in `.nesty/` with restrictive permissions; directory is gitignored.
- Do not expose admin or console secrets to browser clients.
- Use `env` or `file` bootstrap modes for production self-host deployments.
