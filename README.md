<p align="center">
  <img src="public/NestyAI_Full.svg" alt="NestyAI" width="560" />
</p>

<p align="center">
  <strong>NestyAI</strong><br/>
  Production-ready personal FastAPI AI Gateway with OpenAI-compatible chat API.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-Production%20Ready-009688" alt="FastAPI" />
  <img src="https://img.shields.io/badge/tests-392%20passed-brightgreen" alt="Tests" />
  <img src="https://img.shields.io/badge/API-OpenAI%20Compatible-orange" alt="OpenAI Compatible" />
  <img src="https://img.shields.io/badge/streaming-SSE-ff9800" alt="SSE" />
  <img src="https://img.shields.io/badge/version-1.0.0-blue" alt="Version" />
</p>

---

## Overview

NestyAI is a **personal-first, self-hostable AI Gateway** focused on developer experience and light, robust local-first deployments.

### What NestyAI Is:
- A personal/local-first OpenAI-compatible proxy (`POST /v1/chat/completions`)
- A deterministic router with automatic failover between Groq, OpenRouter, and NVIDIA
- A safety-first gatekeeper featuring `InputGuard`, `ContextGuard`, and `OutputGuard`
- A conversation memory keeper using local SQLite FTS5 for message search and summaries
- An optional local semantic recall platform using in-DB cosine similarity calculations

### What NestyAI Is Not:
- An enterprise-scale gateway out of the box (no built-in OAuth/multi-tenancy/billing/dashboard UI)
- An integration with external high-performance vector databases (keeps all vectors in SQLite)
- A high-throughput proxy for large teams without custom tuning or database pooling

Users who need enterprise capabilities are encouraged to fork, extend, and adapt the repository to their needs.

Current status: **Phase 10.0 complete — Gateway Core v1 Stabilization.**

---

## Core Features

- OpenAI-compatible chat API
- streaming and non-streaming support
- stable public model aliases:
  - `nesty-flash-1.0`
  - `nesty-combined-1.0`
  - `nesty-pro-1.0`
- provider fallback routing (Groq/OpenRouter/NVIDIA)
- InputGuard, OutputGuard, ContextGuard
- API key auth, rate limit, quota, usage tracking
- conversation store (SQLite), pagination, export, archive filters
- conversation summary/compression modes (`auto`, `off`, `force`)
- SQLite FTS5 message search with fallback to LIKE
- runtime model config overrides via internal API
- embedding provider abstraction + optional message embedding
- semantic recall (optional, local cosine similarity over stored embeddings)
- memory safety controls (pinned/excluded/tags + recall dedup)
- provider health diagnostics and benchmark utilities

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

### 3) Diagnose Setup

Verify that files, environment variables, database connectivity, and FTS5 capabilities are working:

```bash
python scripts/doctor.py
```

### 4) Run

```bash
python run.py
```

Server:

- `http://127.0.0.1:8000`

---

## API Quick Examples

### Non-stream chat

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "Hello NestyAI"}],
    "search": "off"
  }'
```

### Streaming chat

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

## Model Profiles

- `nesty-flash-1.0`: fastest lightweight profile, concise, conservative automation.
- `nesty-combined-1.0`: balanced default profile for general chat.
- `nesty-pro-1.0`: highest-quality profile, optional non-streaming multi-model orchestration.

Public API remains stable with alias-based model selection. Internal upstream provider/model chains are configurable.

---

## Conversation Memory and Search

### Conversation capabilities

- store/reuse conversation sessions
- summary compression
- controls:
  - summarize
  - clear
  - reset-summary
  - export
- pagination and filters
- ownership access control

### Search capabilities

- conversation search endpoint: `GET /v1/conversations/search`
- message search backend modes:
  - `backend=auto` (FTS5 then LIKE fallback)
  - `backend=fts`
  - `backend=like`
- FTS search returns rank/snippet metadata

Rebuild FTS:

```bash
python scripts/rebuild_fts.py
python scripts/rebuild_fts.py --db data/nesty.db
```

---

## Embeddings and Semantic Recall (Optional)

### Embedding abstraction (Phase 7.1)

- provider abstraction:
  - OpenRouter embeddings
  - NVIDIA embeddings foundation
  - NoOp provider for deterministic tests
- embedding records stored in SQLite (`embedding_records`)
- optional best-effort message embedding after message storage

### Semantic recall (Phase 7.2)

- disabled by default
- local cosine similarity over stored embeddings (no external vector DB)
- optional request mode:
  - `semantic_recall=auto`
  - `semantic_recall=on`
  - `semantic_recall=off`
- recall context is treated as untrusted memory context, not system instruction

Semantic recall requires:

- embeddings enabled
- stored embeddings available (live traffic or backfill)

### Memory safety and recall controls (Phase 7.3)

- message-level memory controls:
  - `memory_pinned`: boosts semantic recall ranking slightly
  - `memory_excluded`: never returned by semantic recall
  - `memory_tags`: optional safe metadata tags
- recall safety controls:
  - pinned boost is capped at score `1.0`
  - dedup by message id + near-identical normalized content
  - dedup against recent history and summary-like snippets
  - max recalled snippets per conversation
- semantic memory remains contextual-only (never treated as instruction)
- no raw vectors exposed in public/internal responses
- no cross-key recall exposure (ownership boundary enforced)
- excluded-message embeddings can be cleaned via `scripts/cleanup_memory.py`

### Provider health diagnostics (Phase 8.0)

- lightweight provider/model diagnostics with tiny prompt checks
- diagnostics for model aliases and orchestration roles
- local SQLite storage of diagnostic results (`provider_health_checks`)
- internal admin diagnostics endpoints for health listing and check execution
- benchmark scripts for provider chains and latest health summaries
- diagnostics are isolated from normal chat:
  - no tools
  - no search
  - no conversation memory
  - no user conversation payload reuse
- operational notes:
  - diagnostics consume normal provider quota
  - OpenRouter free models may be rate-limited
  - results can vary by time, region, and provider availability

### Diagnostics polish and health-aware routing (Phase 8.1)

- health summary endpoint and script improvements for ops visibility
- optional health-aware routing gate for provider chains (disabled by default)
- freshness and staleness controls:
  - `PROVIDER_HEALTH_TTL_SECONDS`
  - `PROVIDER_HEALTH_FAILURE_THRESHOLD`
  - `PROVIDER_HEALTH_SKIP_STATUSES`
  - `PROVIDER_HEALTH_ALLOW_STALE_AFTER_SECONDS`
- fallback behavior:
  - if all targets are marked unhealthy and strict mode is off, router falls back to normal chain
  - strict mode can block all skipped targets safely with structured error
- stream and non-stream flows keep the same API contract; provider health metadata is additive only

### Provider reliability scoring (Phase 8.3)

- Local, passive reliability scoring computed from diagnostic sample history (between `0.0` and `1.0`).
- No change to runtime provider routing decisions (passive-only metadata in this phase).
- Integrates weights for:
  - **Recency**: Recent statuses are decay-weighted higher than older checks.
  - **Latency**: Mild penalty applied to high-latency successful checks.
  - **Stability**: Variation analysis of success rates across check windows.
- Confidence levels:
  - `insufficient_data`: Fewer than `PROVIDER_RELIABILITY_MIN_CHECKS` checks.
  - `low`: Min checks to 5 checks.
  - `medium`: 6 to 10 checks.
  - `high`: Greater than 10 checks.
- View scores via CLI summary tool:
  ```bash
  python scripts/provider_health_summary.py --show-reliability
  ```
- Summary endpoint: Reliability arrays are appended to `/internal/diagnostics/provider-health/summary`.

### API Stability, Compatibility, and SDK Prep (Phase 9.0)

- **Stable Contracts**: Core contracts for completions, models, and conversations frozen and documented in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).
- **Error Specification**: Standardized error responses detailed in [`docs/ERRORS.md`](docs/ERRORS.md). All gateway responses map standard codes with type indicators.
- **OpenAPI Schema Exporter**: Export the API schema locally using `python scripts/export_openapi.py`.
- **Blueprints for SDKs**: SDK preparatory patterns for Python, JS/TS, and Android documented in [`docs/SDK_PREP.md`](docs/SDK_PREP.md).

### Final API Polish and Backward Compatibility Freeze (Phase 9.1)

- **Central version**: `app/version.py` exports `VERSION = "1.0.0"` and `API_VERSION = "v1"`.
- **Version header**: All responses carry `X-Nesty-API-Version` for easy client detection.
- **Version fields**: `/health`, `/ready`, and `/` all return `version` and `api_version` fields.
- **OpenAPI check flag**: `python scripts/export_openapi.py --check` validates docs/openapi.json is up-to-date.
- **Compatibility contract**: [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md) documents the stability guarantee and frozen v1 field list.
- **Contract snapshot tests**: `tests/test_backward_compatibility_freeze.py` asserts all guaranteed fields exist and keep correct types.

### Gateway Core v1 Stabilization (Phase 10.0)

- **Release version**: Bumped `VERSION` from `1.0.0-rc1` to final `1.0.0` release.
- **OpenAPI Schema Sync**: Regenerated and validated the public API OpenAPI schema definition (`docs/openapi.json`).
- **Release check**: Verified all setup, doctor, and backward compatibility tests run clean.

---

These endpoints are **server-to-server internal APIs** and should not be exposed to browsers directly.

### Internal model config API (Phase 7.0c)

- `GET /internal/model-configs`
- `GET /internal/model-configs/{model_id}`
- `PATCH /internal/model-configs/{model_id}`
- `POST /internal/model-configs/{model_id}/reset`
- `POST /internal/model-configs/{model_id}/test`
- `GET /internal/model-configs/audit`

### Internal embedding utilities

- `POST /internal/embeddings/test`
- `POST /internal/embeddings/recall-test`

### Internal diagnostics utilities (Phase 8.0)

- `GET /internal/diagnostics/provider-health`
- `GET /internal/diagnostics/provider-health/latest`
- `GET /internal/diagnostics/provider-health/summary`
- `POST /internal/diagnostics/provider-health/check`
- `POST /internal/diagnostics/provider-model/check`

Protected by:

- `INTERNAL_ADMIN_ENABLED`
- `NESTY_INTERNAL_ADMIN_TOKEN`

---

## Production Checklist

Recommended baseline:

```bash
APP_ENV=production
REQUIRE_API_KEY=true
NESTY_API_KEY_HASH_SECRET=replace_with_a_strong_secret
RATE_LIMIT_ENABLED=true
SECURITY_HEADERS_ENABLED=true
TRUSTED_HOSTS=your-api.example.com
CORS_ENABLED=true
CORS_ALLOW_ORIGINS=https://your-app.example.com
SAFE_DEBUG_AUTH=false
INTERNAL_ADMIN_ENABLED=false
```

Also:

- never commit `.env`
- never commit `data/nesty.db`
- avoid wildcard CORS in production
- do not expose internal admin token to client/browser code

---

## Environment Variables (Major Groups)

### Core and providers

- `APP_NAME`, `APP_VERSION`, `APP_ENV`
- `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`
- `NVIDIA_BASE_URL`

### Security and quota

- `REQUIRE_API_KEY`
- `NESTY_API_KEY_HASH_SECRET`
- `RATE_LIMIT_ENABLED`, `RATE_LIMIT_REQUESTS_PER_MINUTE`
- CORS/trusted-host/body-size/security-header settings

### Conversation memory

- `CONVERSATION_HISTORY_*`
- `CONVERSATION_SUMMARY_*`

### Nesty Pro orchestration

- `NESTY_PRO_ORCHESTRATION_ENABLED`
- `NESTY_PRO_ORCHESTRATION_MAX_INTERNAL_CALLS`
- `NESTY_PRO_ORCHESTRATION_COMPLEXITY_MIN_SCORE`
- `NESTY_PRO_ORCHESTRATION_ROLE_TIMEOUT_SECONDS`
- `NESTY_PRO_ORCHESTRATION_INCLUDE_ROLE_LATENCY`

### Embeddings

- `EMBEDDINGS_ENABLED`
- `EMBEDDINGS_PROVIDER`
- `EMBEDDINGS_MODEL`
- `EMBEDDINGS_DIMENSIONS`
- `EMBEDDINGS_TIMEOUT_SECONDS`
- `EMBEDDINGS_MAX_INPUT_CHARS`
- `EMBEDDINGS_STORE_MESSAGE_EMBEDDINGS`
- `EMBEDDINGS_BACKFILL_BATCH_SIZE`

### Semantic recall

- `SEMANTIC_RECALL_ENABLED`
- `SEMANTIC_RECALL_TOP_K`
- `SEMANTIC_RECALL_MIN_SCORE`
- `SEMANTIC_RECALL_MAX_CONTEXT_CHARS`
- `SEMANTIC_RECALL_SCOPE`
- `SEMANTIC_RECALL_INCLUDE_ROLES`
- `SEMANTIC_RECALL_EXCLUDE_CURRENT_CONVERSATION_RECENT`
- `SEMANTIC_RECALL_CANDIDATE_LIMIT`
- `SEMANTIC_RECALL_PINNED_BOOST`
- `SEMANTIC_RECALL_DEDUP_SIMILARITY`
- `SEMANTIC_RECALL_MAX_PER_CONVERSATION`
- `SEMANTIC_RECALL_EXCLUDE_MEMORY_EXCLUDED`

### Diagnostics

- `DIAGNOSTICS_ENABLED`
- `DIAGNOSTICS_DEFAULT_TIMEOUT_SECONDS`
- `DIAGNOSTICS_TEST_MAX_TOKENS`
- `DIAGNOSTICS_SAVE_RESULTS`
- `DIAGNOSTICS_OUTPUT_PREVIEW_CHARS`

### Health-aware routing

- `PROVIDER_HEALTH_AWARE_ROUTING`
- `PROVIDER_HEALTH_STRICT_MODE`
- `PROVIDER_HEALTH_TTL_SECONDS`
- `PROVIDER_HEALTH_FAILURE_THRESHOLD`
- `PROVIDER_HEALTH_SKIP_STATUSES`
- `PROVIDER_HEALTH_ALLOW_STALE_AFTER_SECONDS`

See [`.env.example`](.env.example) for full list.

---

## Scripts

- `python scripts/rebuild_fts.py`
- `python scripts/rebuild_embeddings.py`
- `python scripts/test_embedding_provider.py`
- `python scripts/test_semantic_recall.py --text "What did I say earlier?"`
- `python scripts/evaluate_semantic_recall.py --query "What did I say earlier?" --show-content-preview`
- `python scripts/cleanup_memory.py --delete-embeddings-for-excluded`
- `python scripts/benchmark_provider_chains.py --include-roles`
- `python scripts/benchmark_provider_chains.py --include-roles --only-unhealthy`
- `python scripts/provider_health_summary.py --limit 50 --since-seconds 3600`
- `python scripts/export_openapi.py` (exports OpenAPI schema JSON)

Scheduler examples (manual ops wiring, no built-in scheduler):

- Windows Task Scheduler:
  - `python scripts/benchmark_provider_chains.py --include-roles`
- Linux cron:
  - `*/30 * * * * cd /path/to/nesty-ai && .venv/bin/python scripts/benchmark_provider_chains.py --include-roles`
- Docker Compose:
  - `docker compose exec nesty-ai python scripts/benchmark_provider_chains.py --include-roles`

Operational warning:

- diagnostics consume provider quota
- keep diagnostic intervals conservative
- free-tier providers may rate-limit or throttle
- health-aware routing is optional and disabled by default

---

## Memory Controls API Examples

```bash
curl -X PATCH "http://127.0.0.1:8000/v1/conversations/<conversation_id>/messages/<message_id>/memory" \
  -H "Content-Type: application/json" \
  -d '{
    "pinned": true,
    "excluded": false,
    "tags": ["project", "important"]
  }'
```

```bash
curl "http://127.0.0.1:8000/v1/conversations/memory-controls?pinned=true&limit=20&offset=0"
```

---

## API Surface
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

### Internal (admin token required)

- model-config endpoints under `/internal/model-configs/*`
- embedding utility endpoints under `/internal/embeddings/*`
- diagnostics endpoints under `/internal/diagnostics/*`

---

## Quality Status

- test suite: **392 passed**
- streaming SSE contract: enabled
- FTS fallback behavior: enabled
- semantic recall: optional, disabled by default
- provider diagnostics: optional and internal-admin-only

---

## Scope Notes

- no external vector DB in current phase
- no dashboard/admin UI in backend repo
- no billing/OAuth
- no semantic recall injection if feature disabled
- chat provider chains remain separate from embedding config

---

## Docs

- Technical notes: [`docs/README_TECHNICAL.md`](docs/README_TECHNICAL.md)
- Deployment guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- Release checklist: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)
- API contract specs: [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md)
- Standard error spec: [`docs/ERRORS.md`](docs/ERRORS.md)
- SDK preparation blueprints: [`docs/SDK_PREP.md`](docs/SDK_PREP.md)
- Compatibility contract: [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md)
- Examples: [`examples/`](examples)

---

## Next Phase

Recommended next target: **Production monitoring, Observability metrics, and alerting hooks.**
