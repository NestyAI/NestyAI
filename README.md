# NestyAI (Phase 4: API Key Auth, Rate Limit, Usage Tracking)

NestyAI is a personal FastAPI AI Gateway with OpenAI-compatible chat, provider fallback routing, safety guards, web search, and server-side tools.

## Core Endpoints

- `GET /`
- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`

## Model Aliases

- `nesty-flash-1.0`
- `nesty-combined-1.0`
- `nesty-pro-1.0`

## Tool System Overview

- Central `ToolRegistry`
- Rule-based `ToolPlanner`
- Tools selected server-side only
- Tool outputs sanitized by `ContextGuard` as untrusted external context
- `tools` request mode:
  - `"auto"`
  - `"off"`
  - `list[str]`

Supported tools:

- `calculator`
- `wikipedia_lookup`
- `package_version_lookup`
- `weather_lookup` (Open-Meteo)
- `exchange_rate` (Frankfurter)

## Cache Overview

In-memory TTL cache for tool/search reliability:

- In-memory only
- No Redis yet
- Cache resets on server restart

## Phase 4 Auth Overview

- API keys are stored as hashes in local SQLite (`data/nesty.db` by default).
- Chat endpoint (`/v1/chat/completions`) supports:
  - `Authorization: Bearer <key>`
  - `X-Nesty-API-Key: <key>`
- If `REQUIRE_API_KEY=true`, chat always requires a valid active key.
- `/health` and `/v1/models` remain public when:
  - `PUBLIC_HEALTH=true`
  - `PUBLIC_MODELS=true`
- Recommended for deployment:
  - `REQUIRE_API_KEY=true`
  - set `NESTY_API_KEY_HASH_SECRET`

If `NESTY_API_KEY_HASH_SECRET` is set, key hashes use HMAC-SHA256.
If unset, fallback is plain SHA256 (works for local dev, not recommended for deployment).

## Rate Limit and Quota

- In-memory rate limiter (per API key, or per client IP when unauthenticated).
- Config:
  - `RATE_LIMIT_ENABLED=true`
  - `RATE_LIMIT_REQUESTS_PER_MINUTE=60`
- Quotas are request-count based (not token billing):
  - `daily_limit`
  - `monthly_limit`
- Quota checks apply per API key.

## Usage Tracking

Each chat request attempts to write a usage log row:

- `api_key_id` (or `null` for unauthenticated calls)
- `request_id`
- `model`, `provider`
- token usage if available
- `tools_used`, `search_used`
- `latency_ms`
- `status` (`success` / `error`)
- `error_code` when present

NestyAI does not log raw API keys, raw prompts, or raw model outputs in usage storage.

## Setup

1. Create Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

3. Create `.env` from `.env.example` and configure keys:

- Provider keys:
  - `GROQ_API_KEY`
  - `OPENROUTER_API_KEY`
  - `NVIDIA_API_KEY` (optional)
- Phase 4:
  - `NESTY_DB_PATH=data/nesty.db`
  - `NESTY_API_KEY_HASH_SECRET=...` (recommended)
  - `REQUIRE_API_KEY=false` (set `true` in deployment)
  - `PUBLIC_HEALTH=true`
  - `PUBLIC_MODELS=true`
  - `RATE_LIMIT_ENABLED=true`
  - `RATE_LIMIT_REQUESTS_PER_MINUTE=60`
  - `SAFE_DEBUG_AUTH=false`

## API Key Scripts

Create key:

```bash
python scripts/create_api_key.py --name local-dev --env dev --daily-limit 1000 --models nesty-flash-1.0,nesty-combined-1.0
```

List keys:

```bash
python scripts/list_api_keys.py
```

Revoke key:

```bash
python scripts/revoke_api_key.py --id key_xxxxxxxxxxxxxxxx
```

Usage summary:

```bash
python scripts/usage_summary.py --days 7
```

## Call Chat with API Key

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer nsk_dev_xxx" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "Hello"}],
    "search": "off",
    "tools": "auto"
  }'
```

## Streaming (Phase 5)

NestyAI now supports `stream=true` on `/v1/chat/completions` using Server-Sent Events (SSE).

Response stream format:

- `data: {json chunk}`
- `data: [DONE]`

Chunk object shape:

- `object: "chat.completion.chunk"`
- `choices[0].delta.content` for text deltas
- final chunk includes `finish_reason`

Metadata event:

- Before `[DONE]`, NestyAI emits:
  - `object: "chat.completion.metadata"`
  - includes `guard`, `tools`, `sources`, `usage`

Streaming example (Windows PowerShell):

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/chat/completions" ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer YOUR_KEY" ^
  -d "{\"model\":\"nesty-combined-1.0\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a short intro about NestyAI\"}],\"stream\":true,\"search\":\"off\",\"tools\":\"off\"}"
```

Streaming notes:

- OutputGuard currently runs after stream completion (MVP safety model).
- If output sanitation is detected, stream metadata indicates redaction and a guard notice chunk can be emitted.
- Usage logging is recorded after stream completion when possible.

## Streaming Client Examples (Phase 5.1)

Reference client examples are available under `examples/`:

- Python:
  - `examples/python/chat_non_stream.py`
  - `examples/python/chat_stream.py`
- JavaScript (Node 18+):
  - `examples/javascript/chat_non_stream.js`
  - `examples/javascript/chat_stream_fetch.js`
- Kotlin/Android reference:
  - `examples/kotlin/android_sse_example.kt`

Run Python stream example:

```bash
python examples/python/chat_stream.py
```

Run JavaScript stream example:

```bash
node examples/javascript/chat_stream_fetch.js
```

Stream event types:

- `chat.completion.chunk`: incremental assistant delta tokens.
- `chat.completion.metadata`: final NestyAI metadata (`guard`, `tools`, `sources`, `usage`).
- `chat.completion.error`: stream interruption notification.
- `[DONE]`: stream completion marker.

Metadata may include:

- `guard`
- `tools`
- `sources`
- `usage`

CORS note:

- If you call NestyAI directly from browser/mobile web in development, configure CORS intentionally.
- Do not use wildcard CORS in production when private API keys are involved.

## Run

```bash
python run.py
```

## Run Tests

```bash
python -m pytest -q
```

## Phase 4.1 Runtime Verification

Run full test suite:

```bash
python -m pytest -q
```

Verify scripts:

```bash
python scripts/create_api_key.py --name local-dev --env dev --daily-limit 1000 --models nesty-flash-1.0,nesty-combined-1.0
python scripts/list_api_keys.py
python scripts/usage_summary.py --days 7
```

Manual auth verification:

```bash
REQUIRE_API_KEY=true
PUBLIC_HEALTH=true
PUBLIC_MODELS=true
```

Then verify:

- `GET /health` is public.
- `GET /v1/models` is public.
- `POST /v1/chat/completions` requires API key.

Runtime note:

- FastAPI startup init is migrated from `@app.on_event("startup")` to lifespan.
- A specific TestClient deprecation warning may be filtered in pytest when it is upstream-only.
- In restricted environments, pytest cache warnings can appear and do not affect pass/fail.

Troubleshooting:

- If `.pytest_cache` cannot be written due to environment restrictions, test outcomes are still valid.
- If `python` is not in PATH, run tests with your interpreter launcher path directly.

## Deployment Recommendations

- Set `REQUIRE_API_KEY=true`.
- Set `NESTY_API_KEY_HASH_SECRET`.
- Do not commit `.env`.
- Do not commit `data/nesty.db`.
- Keep `SAFE_DEBUG_AUTH=false` in production.

## Notes

- No billing implementation in Phase 4.
- No user accounts/login/OAuth in Phase 4.
- No admin HTTP endpoints yet (scripts only). Admin API can be Phase 4.5.
