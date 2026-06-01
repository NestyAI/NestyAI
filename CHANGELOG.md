# Changelog

All notable changes to the NestyAI project are documented in this file.

Tracking rule:
- This file is the public, versioned feature changelog.
- Each version entry should describe user-visible capabilities and behavior in plain language.
- Internal architecture notes and deep technical change logs belong in `AI.md`.

## [1.0.4] - 2026-06-01

### Added
- Added safe, structured metadata fields to `OrchestrationInfo` response: `completed_roles`, `failed_roles`, `skipped_roles`, `fallback_reason`, `streaming_fallback`, and `total_latency_ms`.
- Enabled the Pydantic schema to accept both string and boolean representation for `orchestration.requested` to maintain maximum client compatibility.
- Implemented consistent orchestration `mode` categorisation: `"off"`, `"single"`, `"reduced"`, `"full"`, `"fallback"`, or `"unknown"`.
- Improved multi-model orchestrator execution tracking to capture per-role latencies and completed vs failed execution states during error recovery.

### Security
- Enforced strict output sanitisation on response metadata to guarantee that no internal prompts, role system instructions, provider secrets, API keys, or raw exception stack traces/tracebacks are exposed to clients.

## [1.0.2] - Unreleased

### Added
- Added optional Cloudflare Tunnel deployment preset with Docker Compose sidecar support and Pterodactyl/container-panel environment variables.
- Added optional runtime Cloudflare Tunnel launcher for Pterodactyl/container-panel deployments.
- Added optional ephemeral startup API key generation for Nesty Console in Pterodactyl/container-panel deployments where scripts cannot be run interactively.

### Documentation
- Documented HTTPS tunnel deployment reminders for CORS, trusted hosts, tunnel secrets, and future Nesty Console/NestyChat usage.
- Documented how Console users can copy the ephemeral key from Gateway startup logs and update Console credentials after Gateway restarts.

## [Phase 10.0] - Gateway Core v1 Stabilization
- Bump version to `1.0.0` for official stable release.
- Update compatibility guarantees and API contract references.
- Regenerate public API OpenAPI schemas (`docs/openapi.json`).
- Ensure all diagnostics, setup checks, and backward compatibility contract tests pass.

## [Phase 9.1] - Final API Polish and Backward Compatibility Freeze
- Stamp every HTTP response with `X-Nesty-API-Version` response header.
- Append `version` and `api_version` to root, `/health`, and `/ready` responses.
- Define explicit API compatibility guarantee in `docs/COMPATIBILITY.md`.
- Implement API contract snapshot test suite to prevent regressions.
- Add check mechanism to OpenAPI exporter script for continuous integration.

## [Phase 9.0] - API Stability, Compatibility, and SDK Prep
- Document request and response structures for all public endpoints in `docs/API_CONTRACT.md`.
- Establish standard JSON error payload envelope and code catalog in `docs/ERRORS.md`.
- Provide client SDK preparation blueprints for future client development in `docs/SDK_PREP.md`.
- Add OpenAPI JSON schema exporter script `scripts/export_openapi.py`.
- Polish JS and Python client examples to run against the mock router environment.

## [Phase 8.3] - Provider Reliability Scoring
- Implement passive reliability scoring for providers and aliases.
- Track success/failure latency windows and calculate confidence levels.
- Add reliability metrics to CLI summary tools and internal admin endpoints.
- Ensure safe database initialization and fallback paths for older SQLite runtimes.

## [Phase 8.2] - Production Readiness Polish & Release Hygiene
- Add warning-level checks for missing keys instead of raising errors during app initialization.
- Create automated diagnostic doctor script `scripts/doctor.py`.
- Formulate standardized pre-release checklist in `docs/RELEASE_CHECKLIST.md`.

## [Phase 8.1] - Health-Aware Routing & Diagnostics Polish
- Add health-aware routing capabilities to route chat requests away from unhealthy providers.
- Implement provider health summary endpoint and CLI reporting.
- Polish provider diagnostics script error checking.
- Refactor test suite mocks to prevent unwanted health DB access in test runs.

## [Phase 8.0] - Provider Diagnostics
- Implement lightweight provider and model chẩn đoán checks using small prompts.
- Save diagnostics outputs locally under `provider_health_checks` table.
- Create admin-protected chẩn đoán utility endpoints.
- Add provider benchmark CLI utility scripts.

## [Phase 7.3] - Memory Safety & Pinned Recall Boosts
- Add support for message-level memory overrides (`memory_pinned`, `memory_excluded`, `memory_tags`).
- Implement recall filters to prevent duplicated or overly redundant retrieval items.
- Ensure cross-user and cross-key memory boundaries remain strictly isolated.

## [Phase 7.2] - Local Semantic Recall
- Add local cosine similarity retrieval over SQLite-stored embedding records.
- Implement contextual-only memory injections for completions.
- Add test utilities to evaluate similarity performance.

## [Phase 7.1] - Embedding Abstraction
- Support OpenRouter and NVIDIA embedding providers.
- Save message-level embeddings to `embedding_records` automatically on chat completions.
- Implement CLI tool to backfill and rebuild database embeddings.

## [Phase 7.0d] - Provider Chain Tuning
- Configure stable provider fallbacks for `nesty-flash-1.0` and `nesty-combined-1.0` aliases.

## [Phase 7.0c] - Runtime Model Config API
- Add admin endpoints (`/internal/model-configs/*`) to fetch, patch, reset, and test model routing strategies on the fly.
- Maintain configuration audits in `model_config_audit_logs`.

## [Phase 7.0b] - Orchestration Cost Safety
- Enforce call boundaries and token limit gates during deep synthesis orchestration roles.

## [Phase 7.0a] - Model Behavior & Pro Orchestration
- Build multi-model synthesis strategy for the `nesty-pro-1.0` profile.
- Orchestrate planner, researcher, critic, and finalizer roles.

## [Phase 7.0] - SQLite FTS Message Search
- Add SQLite FTS5 table indexing for conversation messages with keyword LIKE fallback.

## [Phase 6.3] - Conversation Search Endpoints
- Implement `GET /v1/conversations/search` endpoint to query historic sessions.

## [Phase 6.2] - Conversation Controls & Export
- Implement conversation controls: clear, reset summary, and export endpoints.

## [Phase 6.1] - Session Summaries
- Add automatic contextual summarization (`summary=auto|off|force`) when message thresholds are crossed.

## [Phase 6.0] - Conversation Sessions
- Implement sqlite-backed stateful chat sessions. Clients can query and load previous history by passing `conversation_id`.

## [Phase 5.2] - Deployment Hardening
- Implement BodySizeLimitMiddleware, TrustedHostMiddleware, and SecurityHeadersMiddleware.
- Enforce strict wildcard CORS policies in production.

## [Phase 5.1] - Client Examples
- Add stream/non-stream implementation examples in Python, JavaScript, and Kotlin/Android.

## [Phase 5] - Streaming Completions
- Implement SSE (Server-Sent Events) streaming contract for model responses.

## [Phase 4.1] - Runtime Polish
- Hardened model router and fallback selection rules.

## [Phase 4] - Auth, Rate Limiting & Quota
- Implement API key authorization via SHA-256 HMAC prefix verification.
- Enforce rate-limits and daily/monthly quotas.

## [Phase 3.5] - Cache & Data Providers
- Implement caching for internal Web search and currency exchanges.

## [Phase 3] - Tool Integration
- Integrate calculator, Wikipedia, and weather lookup tools.

## [Phase 2.5] - QA & Hardening
- Stabilize fallback routing logic and add basic tests.

## [Phase 2] - Search & Context Guard
- Implement InputGuard, OutputGuard, and ContextGuard modules.

## [Phase 1] - MVP Gateway
- Initialize FastAPI app setup with basic chat completion route (`POST /v1/chat/completions`).
