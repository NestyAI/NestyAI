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
  <img src="https://img.shields.io/badge/version-1.5.1-blue" alt="Version" />
  <img src="https://img.shields.io/badge/tests-529%20passed-brightgreen" alt="Tests" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache-2.0" />
</p>

<p align="center">
  <strong>Ship faster.</strong> Route smarter. Stay in control.
</p>

---

## Overview

NestyAI is a self-hosted AI gateway for teams and builders who want OpenAI-compatible chat APIs without losing control over routing, safety, memory, and operations.

It is designed for practical production use:

- OpenAI-compatible `POST /v1/chat/completions`
- Stable public model aliases for predictable client behavior
- Deterministic provider fallback across Groq, OpenRouter, NVIDIA, and Ollama Cloud
- Safe input, context, and output guards
- Conversation memory with summaries, search, and semantic recall
- Safe additive metadata for retrieval, orchestration, and answer quality
- Optional deployment polish for Cloudflare Tunnel and panel environments

If you need a gateway that feels lean, but still behaves like a serious production service, this is the sweet spot.

---

## What Makes It Useful

| Area | What You Get |
| --- | --- |
| API | OpenAI-compatible chat completions with streaming SSE |
| Routing | Provider chains, alias mapping, and deterministic fallback |
| Safety | InputGuard, ContextGuard, OutputGuard, and answer-quality guard metadata |
| Memory | Conversations, summaries, archive/export, search, pinned/excluded memory |
| Retrieval | FTS5 search, hybrid context assembly, semantic recall, and tool context |
| Ops | Diagnostics, doctor checks, provider health, and OpenAPI export |
| Deployment | Docker, local Python, and panel-friendly runtime support |

---

## Current Release Snapshot

- Version: `1.5.1` — Dynamic OpenAI-Compatible Provider Runtime
- Public API: OpenAI-compatible provider surface at `/v1` (unchanged)
- Runtime providers: register OpenAI-compatible endpoints via internal console APIs
- Built-in vs runtime: non-OpenAI-compatible providers still require built-in adapter code

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
- `NVIDIA_API_KEY` optional
- `OLLAMA_API_KEY` optional

### 3) Validate

```bash
python scripts/doctor.py
```

### 4) Run

```bash
python run.py
```

Default URL:

- `http://127.0.0.1:8000`

### 5) Verify API Schema

```bash
python scripts/export_openapi.py --check
```

---

## Chat API Examples

### Non-stream request

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "Hello NestyAI"}],
    "search": "off"
  }'
```

### Streaming request

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

The streaming response ends with a metadata event and then `data: [DONE]`.

---

## Model Aliases

- `nesty-flash-1.0` - fastest lightweight profile for concise responses
- `nesty-combined-1.0` - balanced default profile for most workloads
- `nesty-pro-1.0` - highest-quality profile with optional non-stream multi-model orchestration

Aliases stay stable even when provider internals change behind them.

---

## Memory and Retrieval

NestyAI keeps conversation memory useful without making it risky:

- Conversation history with summaries
- Search over stored messages and conversations
- Pinned and excluded memory controls
- Optional semantic recall over local SQLite embeddings
- Conservative hybrid context assembly
- Safe deduplication and bounded packing

This release also keeps retrieval metadata summary-level only, so client-visible responses never expose raw prompts, hidden instructions, raw tool payloads, or exception traces.

---

## Deployment Modes

### Local or VM

```bash
python run.py
```

### Docker Compose

```bash
docker compose up --build -d
```

### Cloudflare Tunnel

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for:

- Docker sidecar mode
- Panel-friendly tunnel mode
- Environment variable setup

---

## Panel Bootstrap

For panel environments where interactive shell commands are unreliable, Gateway can generate an ephemeral Console API key at startup.

Enable it in `.env`:

```env
NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED=true
```

Flow:

1. Restart Gateway with `python run.py`.
2. Copy the startup log banner key labeled `EPHEMERAL NESTY CONSOLE API KEY`.
3. Paste it into Nesty Console as `NESTY_API_KEY`.

Notes:

- The ephemeral key rotates on every Gateway restart.
- Previous ephemeral Console keys are revoked automatically.
- Persistent user-created API keys are not affected.

---

## Security Baseline

Recommended production settings:

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

- Never commit `.env` or runtime secrets
- Never commit `data/nesty.db`
- Never expose `NESTY_INTERNAL_ADMIN_TOKEN` to browser or mobile clients

---

## Public API Surface

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

## Documentation Map

- Deployment guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- **External provider integration:** [`docs/OPENAI_COMPATIBLE_PROVIDER.md`](docs/OPENAI_COMPATIBLE_PROVIDER.md)
- Technical notes: [`docs/README_TECHNICAL.md`](docs/README_TECHNICAL.md)
- API contract: [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md)
- Error contract: [`docs/ERRORS.md`](docs/ERRORS.md)
- Compatibility policy: [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md)
- Release checklist: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)
- SDK prep notes: [`docs/SDK_PREP.md`](docs/SDK_PREP.md)
- OpenAPI snapshot: [`docs/openapi.json`](docs/openapi.json)
- Examples: [`examples/`](examples)

---

## Scope Boundaries

NestyAI is intentionally focused:

- No built-in dashboard or admin UI in this backend repo
- No OAuth, billing, or workspace platform by default
- No external vector DB dependency in core architecture

That keeps the gateway small, predictable, and easy to self-host.

---

## License

NestyAI Gateway is licensed under Apache 2.0.

See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

