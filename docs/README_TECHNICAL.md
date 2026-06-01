<p align="center">
  <img src="public/NestyAI_Full.svg" alt="NestyAI" width="520" />
</p>

<p align="center">
  <strong>A personal, production-hardened FastAPI AI Gateway</strong><br/>
  OpenAI-compatible chat, provider fallback, safety guards, tools, streaming, and conversation memory.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-Production%20Ready-009688" alt="FastAPI" />
  <img src="https://img.shields.io/badge/tests-151%20passed-brightgreen" alt="Tests" />
  <img src="https://img.shields.io/badge/streaming-SSE-orange" alt="Streaming SSE" />
  <img src="https://img.shields.io/badge/auth-API%20Key-important" alt="Auth" />
</p>

---

## What Is NestyAI?

NestyAI is a self-hosted AI Gateway for developers who want:

- OpenAI-compatible `/v1/chat/completions`
- multiple provider fallback
- strict input/output/context guardrails
- server-side tools + web search
- API key auth, quota, rate limit, usage tracking
- streaming + stateful conversation memory

It is designed to stay local, lightweight, and testable.

## Core Highlights

- OpenAI-compatible chat API (stream and non-stream)
- Model aliases:
  - `nesty-flash-1.0`
  - `nesty-combined-1.0`
  - `nesty-pro-1.0`
- Multi-provider routing and fallback:
  - Groq
  - OpenRouter
  - NVIDIA (configured route)
  - Ollama Cloud
- Guard stack:
  - `InputGuard`
  - `ContextGuard`
  - `OutputGuard`
- Tool system:
  - `calculator`
  - `wikipedia_lookup`
  - `package_version_lookup`
  - `weather_lookup`
  - `exchange_rate`
- Web search + URL fetch protection (SSRF-aware)
- Conversation memory:
  - `conversation_id` + `store`
  - summary modes: `auto`, `off`, `force`
  - conversation controls: summarize, clear, reset-summary, export
  - conversation search/filter/pagination endpoints
- Production hardening:
  - API key auth
  - rate limit + quota
  - trusted hosts
  - body size limit
  - security headers
  - CORS policy guardrails
- SQLite-based persistence (default: `data/nesty.db`)

## Architecture (High-Level)

1. Client calls `/v1/chat/completions`
2. Auth, allowlist, rate/quota checks
3. Guard + optional search + optional tool execution
4. Provider router selects best available backend
5. Response guard, usage logging, optional conversation save/summarize
6. Return OpenAI-compatible response (JSON or SSE)

## Quick Start (Local)

### 1) Install

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2) Configure

```bash
copy .env.example .env
```

Set at least one provider API key:

- `GROQ_API_KEY`
- `OPENROUTER_API_KEY`
- `NVIDIA_API_KEY` (optional)
- `OLLAMA_API_KEY` (optional)

### 3) Run

```bash
python run.py
```

Server default:

- `http://127.0.0.1:8000`

## Docker Deployment

### Build and run

```bash
docker compose up --build -d
```

### Container notes

- port mapping: `8000:8000`
- persistent DB volume: `./data:/app/data`
- secrets come from `.env` (not baked into image)

## Production Configuration Checklist

Recommended minimum:

```bash
APP_ENV=production
REQUIRE_API_KEY=true
NESTY_API_KEY_HASH_SECRET=replace_with_strong_secret
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=60
SECURITY_HEADERS_ENABLED=true
TRUSTED_HOSTS=your-api.example.com
CORS_ENABLED=true
CORS_ALLOW_ORIGINS=https://your-app.example.com
CORS_ALLOW_CREDENTIALS=false
SAFE_DEBUG_AUTH=false
```

Important:

- never use wildcard CORS (`*`) in production with private API keys
- never commit `.env` or `data/nesty.db`
- keep `ENABLE_HSTS=false` unless HTTPS is guaranteed end-to-end

## API Endpoints

### Base and health

- `GET /`
- `GET /health`
- `GET /ready`

### Models and chat

- `GET /v1/models`
- `POST /v1/chat/completions`

### Conversation management

- `GET /v1/conversations`
- `GET /v1/conversations/search`
- `GET /v1/conversations/{conversation_id}`
- `GET /v1/conversations/{conversation_id}/messages`
- `PATCH /v1/conversations/{conversation_id}`
- `DELETE /v1/conversations/{conversation_id}`
- `POST /v1/conversations/{conversation_id}/summarize`
- `POST /v1/conversations/{conversation_id}/clear`
- `POST /v1/conversations/{conversation_id}/reset-summary`
- `GET /v1/conversations/{conversation_id}/export`

## Chat Usage

### Non-stream

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_NESTY_KEY" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role":"user","content":"Write a short intro for NestyAI."}],
    "search": "off",
    "tools": "auto"
  }'
```

### Streaming (SSE)

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_NESTY_KEY" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role":"user","content":"Give me a concise project update."}],
    "stream": true,
    "search": "off",
    "tools": "off"
  }'
```

Stream emits:

- `chat.completion.chunk`
- `chat.completion.metadata`
- `chat.completion.error` (if interrupted)
- `data: [DONE]`

## Conversation Memory and Summary Modes

`/v1/chat/completions` supports:

- `store: true|false`
- `conversation_id: string|null`
- `summary: "auto" | "off" | "force"`

Behavior:

- `store=false`: stateless request
- `store=true` + no `conversation_id`: create new conversation
- `store=true` + `conversation_id`: load conversation context
- `summary=auto`: normal summary policy
- `summary=off`: disable summary injection and post-response summarize for this request
- `summary=force`: force summarize after this request

## Conversation Listing, Filters, and Search

### List conversations

`GET /v1/conversations`

Query params:

- `limit` (1-100)
- `offset` (>= 0)
- `archived=active|archived|all` (default: `active`)
- `q` (optional keyword, max 200)

### Search endpoint

`GET /v1/conversations/search`

Query params:

- `q` (required, non-empty, max 200)
- `limit` (1-100)
- `offset` (>= 0)
- `scope=conversations|messages|all`

### Message pagination endpoint

`GET /v1/conversations/{conversation_id}/messages`

Query params:

- `limit` (1-100, default 50)
- `offset` (>= 0)
- `order=asc|desc` (default `asc`)

## Security Model

- API key validation via hash/HMAC (recommended secret)
- Model allowlist per API key
- Per-key rate limit and daily/monthly quota
- Guardrails for prompt/context/output sanitation
- Safe logging (no raw API key, no raw provider secrets)
- Conversation ownership isolation across API keys

## Key Scripts

```bash
python scripts/create_api_key.py --name local-dev --env dev --daily-limit 1000 --models nesty-flash-1.0,nesty-combined-1.0
python scripts/list_api_keys.py
python scripts/revoke_api_key.py --id key_xxxxxxxxxxxxxxxx
python scripts/usage_summary.py --days 7
python scripts/list_conversations.py --limit 20
```

Conversation export from script:

```bash
python scripts/list_conversations.py --export conv_xxxxxxxxxxxxxxxx
```

## Testing

Run full suite:

```bash
python -m pytest -q
```

Current baseline: **151 passed**.

## Environment Variables

See `.env.example` for the full list.

High-impact groups:

- Provider keys and request timeout
- Auth/rate/quota (`REQUIRE_API_KEY`, `RATE_LIMIT_*`)
- Deployment hardening (`CORS_*`, `TRUSTED_HOSTS`, `SECURITY_HEADERS_ENABLED`)
- Conversation history (`CONVERSATION_HISTORY_*`)
- Conversation summarization (`CONVERSATION_SUMMARY_*`)

## Client Examples

Under `examples/`:

- Python: stream and non-stream
- JavaScript (Node 18+): stream and non-stream
- Kotlin snippet for Android SSE consumption

## Known Limits (By Design)

- No vector DB / embeddings / semantic memory yet
- No billing, OAuth, or admin dashboard UI
- Keyword search is SQLite LIKE-based (non-semantic)

## Roadmap (Next)

- Phase 7: semantic memory foundation (embeddings + vector retrieval policy)
- background summarization workers
- richer observability and operational metrics

---

If you are deploying this publicly, review CORS, trusted hosts, API key policy, and TLS proxy setup before exposing the endpoint.
