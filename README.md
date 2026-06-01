<p align="center">
  <img src="public/NestyAI_Full.svg" alt="NestyAI" width="560" />
</p>

<p align="center">
  <strong>NestyAI Gateway</strong><br/>
  Production-ready, self-hostable FastAPI AI Gateway with an OpenAI-compatible chat API.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-Production%20Ready-009688" alt="FastAPI" />
  <img src="https://img.shields.io/badge/API-OpenAI%20Compatible-orange" alt="OpenAI Compatible" />
  <img src="https://img.shields.io/badge/streaming-SSE-ff9800" alt="SSE" />
  <img src="https://img.shields.io/badge/version-1.0.4-blue" alt="Version" />
  <img src="https://img.shields.io/badge/tests-413%20passed-brightgreen" alt="Tests" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache-2.0" />
</p>

<p align="center">
  <strong>Ship faster.</strong> Route smarter. Stay in control.
</p>

---

## Why NestyAI

NestyAI is a personal-first AI Gateway designed for people who want the power of multi-provider routing, safety controls, and conversation memory without running a heavyweight platform.

It is optimized for real-world operator constraints:
- You want OpenAI-compatible APIs without vendor lock-in.
- You need reliable fallback behavior when providers throttle or fail.
- You care about safe defaults, observability, and self-hosted control.

In short: NestyAI gives you enterprise-like gateway discipline in a lean, developer-first package.

It gives you:
- OpenAI-compatible `POST /v1/chat/completions`
- Stable public model aliases (`nesty-flash-1.0`, `nesty-combined-1.0`, `nesty-pro-1.0`)
- Deterministic provider fallback across Groq, OpenRouter, and NVIDIA
- Built-in safety guards (input, context, output)
- Local-first memory stack with SQLite, FTS search, summaries, and optional semantic recall
- Optional deployment polish for Cloudflare Tunnel and panel environments

If you are building for a team, product prototype, internal tool, or self-hosted AI workflow and want control without unnecessary complexity, this is the sweet spot.

---

## At A Glance

| Area | What You Get |
| --- | --- |
| API | OpenAI-compatible chat completions + streaming SSE |
| Routing | Provider chain fallback and model alias abstraction |
| Safety | InputGuard, ContextGuard, OutputGuard |
| Auth | API key auth, rate limiting, quota, usage logs |
| Memory | Conversations, summaries, archive/export, search |
| Search | SQLite FTS5 search with safe fallback behavior |
| Embeddings | Optional provider abstraction + local semantic recall |
| Ops | Diagnostics, health summaries, reliability scoring, doctor checks |

---

## Who This Is For

- Builders shipping internal AI features fast, without standing up a full platform team.
- Teams that need OpenAI-compatible APIs plus stronger cost/fallback control.
- Operators running self-hosted AI stacks in Docker, VM, or panel environments.
- Developers who value stable contracts, predictable behavior, and clear deployment knobs.

---

## Architecture Snapshot

```
Client / App
   |
   v
NestyAI Gateway (FastAPI)
   |- InputGuard / ContextGuard / OutputGuard
   |- Router + model alias mapping
   |- Tool planner + safe context injection
   |- API key auth / quota / rate-limit
   |- Conversation memory + summaries + search (SQLite/FTS)
   |- Optional embeddings + semantic recall
   |- Internal diagnostics + health summary
   |
   v
Provider chain (Groq / OpenRouter / NVIDIA) with deterministic fallback
```

---

## What Happens In Production

1. Requests enter through OpenAI-compatible endpoints.
2. Safety guards sanitize sensitive or untrusted content.
3. Router selects alias strategy and provider chain.
4. Gateway executes with fallback + usage/rate/quota accounting.
5. Optional memory/recall/diagnostics enrich reliability and operations visibility.

---

## Quick Start

### 1) Install

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2) Configure

```bash
copy .env.example .env
```

Set at least one provider key:
- `GROQ_API_KEY`
- `OPENROUTER_API_KEY`
- `NVIDIA_API_KEY` (optional)

### 3) Validate Setup

```bash
python scripts/doctor.py
```

### 4) Run

```bash
python run.py
```

Gateway URL:
- `http://127.0.0.1:8000`

### 5) Optional: Export/OpenAPI Consistency Check

```bash
python scripts/export_openapi.py --check
```

---

## API Quick Examples

### Non-stream

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "Hello NestyAI"}],
    "search": "off"
  }'
```

### Streaming SSE

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "Give me a short status update"}],
    "stream": true,
    "tools": "off"
  }'
```

---

## Model Aliases

- `nesty-flash-1.0`: fastest lightweight profile for concise responses.
- `nesty-combined-1.0`: balanced default profile for most workloads.
- `nesty-pro-1.0`: highest-quality profile with optional non-stream multi-model orchestration.

Public aliases are stable. Provider/model internals can evolve behind these aliases.

---

## Deployment Modes

### Local / VM / Bare Metal

Run directly with:
```bash
python run.py
```

### Docker Compose

```bash
docker compose up --build -d
```

### Cloudflare Tunnel (Optional)

Both are documented in detail at [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md):
- Docker sidecar mode (`cloudflared` profile)
- Pterodactyl/container-panel mode (`python run.py` + tunnel env)

---

## Panel Console Bootstrap (Optional)

For panel environments where interactive shell commands are unreliable, Gateway can generate an ephemeral Console API key at startup.

Enable in `.env`:

```env
NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED=true
```

Flow:
1. Restart Gateway (`python run.py`).
2. Copy the startup log banner key (`EPHEMERAL NESTY CONSOLE API KEY`).
3. Paste into Nesty Console as `NESTY_API_KEY`.

Notes:
- The ephemeral key rotates on every Gateway restart.
- Previous ephemeral Console keys are revoked automatically.
- Persistent user-created API keys are not affected.

---

## Security Posture

Recommended production baseline:

```env
APP_ENV=production
REQUIRE_API_KEY=true
NESTY_API_KEY_HASH_SECRET=<set-a-strong-secret>
RATE_LIMIT_ENABLED=true
SECURITY_HEADERS_ENABLED=true
CORS_ENABLED=true
CORS_ALLOW_ORIGINS=https://your-app.example.com
TRUSTED_HOSTS=your-api.example.com
INTERNAL_ADMIN_ENABLED=false
SAFE_DEBUG_AUTH=false
```

Always:
- Never commit `.env` or runtime secrets.
- Never commit `data/nesty.db`.
- Never expose `NESTY_INTERNAL_ADMIN_TOKEN` to browser/mobile clients.

---

## Internal Admin APIs

Internal endpoints are server-to-server only and token-protected:
- `/internal/model-configs/*`
- `/internal/embeddings/*`
- `/internal/diagnostics/*`

Guarded by:
- `INTERNAL_ADMIN_ENABLED`
- `NESTY_INTERNAL_ADMIN_TOKEN`

---

## Memory, Search, and Semantic Recall

### Conversation Features
- Store/reuse sessions
- Summarization (`auto`, `off`, `force`)
- Export, archive filters, clear/reset controls
- Ownership-safe retrieval

### Search
- `GET /v1/conversations/search`
- Backend modes: `auto`, `fts`, `like`
- FTS5-first with fallback behavior

### Optional Semantic Recall
- Local cosine similarity over stored embeddings
- No external vector DB required
- Safe contextual memory usage (never treated as system instruction)

---

## Operations Toolkit

Useful scripts:
- `python scripts/doctor.py`
- `python scripts/export_openapi.py --check`
- `python scripts/create_api_key.py --name <name>`
- `python scripts/list_api_keys.py`
- `python scripts/revoke_api_key.py --id <id>`
- `python scripts/provider_health_summary.py --show-reliability`
- `python scripts/benchmark_provider_chains.py --include-roles`
- `python scripts/rebuild_fts.py`
- `python scripts/rebuild_embeddings.py`

---

## API Surface

Public:
- `GET /health`
- `GET /ready`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /v1/conversations`
- `GET /v1/conversations/search`
- `GET /v1/conversations/memory-controls`
- `GET /v1/conversations/{conversation_id}`
- `GET /v1/conversations/{conversation_id}/messages`
- `PATCH /v1/conversations/{conversation_id}/messages/{message_id}/memory`
- `POST /v1/conversations/{conversation_id}/summarize`
- `POST /v1/conversations/{conversation_id}/clear`
- `POST /v1/conversations/{conversation_id}/reset-summary`
- `GET /v1/conversations/{conversation_id}/export`

---

## Quality Snapshot

- Full suite local snapshot: **411 passed**
- Streaming SSE contract: enabled
- FTS fallback behavior: enabled
- Semantic recall: optional, disabled by default
- Diagnostics: optional, internal-admin-only

---

## Scope Boundaries

NestyAI is intentionally focused:
- No built-in dashboard/admin UI in this backend repo
- No OAuth/billing/multi-tenant workspace platform by default
- No external vector DB dependency in core architecture

Enterprise teams can fork and extend these areas as needed.

---

## Documentation Map

- Deployment guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- Technical notes: [`docs/README_TECHNICAL.md`](docs/README_TECHNICAL.md)
- API contract: [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md)
- Error contract: [`docs/ERRORS.md`](docs/ERRORS.md)
- Compatibility policy: [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md)
- Release checklist: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)
- SDK prep notes: [`docs/SDK_PREP.md`](docs/SDK_PREP.md)
- OpenAPI snapshot: [`docs/openapi.json`](docs/openapi.json)
- Usage examples: [`examples/`](examples)

---

## License

NestyAI Gateway is licensed under Apache 2.0.

See [LICENSE](./LICENSE) and [NOTICE](./NOTICE).

---

## Roadmap Direction

Production monitoring, observability metrics, and alerting hooks.
