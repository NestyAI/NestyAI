# Changelog

All notable changes to the NestyAI project are documented in this file.

Tracking rule:
- This file is the public, versioned feature changelog.
- Each version entry should describe user-visible capabilities and behavior in plain language.
- Internal architecture notes and deep technical change logs belong in `AI.md`.

## [1.4.0] - 2026-06-11

### Added
- Added tolerant OpenAI-compatible provider content extraction for string and multipart `message.content` payloads.
- Added one safe empty-answer retry when retrieval, search, tools, or Pro synthesis context was used but the first final output was empty.
- Added dependency-free search query planner (1–3 focused queries) with improved dedupe, ranking, and safe search metadata.
- Added compact internal `lifecycle_events` metadata for search, tools, provider selection, answer quality, and chat completion (no outbound webhooks).

### Changed
- Improved generic tool planner reasons (`matched_<tool>`), registry trigger keyword exposure, and safer tool execution metadata (`error_code`, `result_chars`).
- Improved search/tool coordination so deterministic tool intents can skip redundant web search unless `search=on`.
- Extended safe metadata for search (`queries`, `provider`, `latency_ms`, `filtered_result_count`, `cache_hit`, `context_chars`) and answer quality (`empty_before_fallback`, `retry_attempted`).

### Fixed
- Fixed repeated `empty_answer` fallback when providers returned valid multipart content that was previously coerced to empty text.
- Preserved surrounding user-facing prose when removing internal tool markup blocks.

### Security
- Lifecycle events and expanded metadata remain sanitized: no prompts, secrets, stack traces, raw provider payloads, chain-of-thought, or internal tool markup.

## [1.3.1] - Unreleased

### Added
- Added provider-style API key and usage troubleshooting documentation for external integrations.
- Added public `X-Request-ID` correlation header on Gateway responses for safer external debugging.
- Added rate-limit response headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) on chat routes where the limiter runs.

### Changed
- Revoked API keys now return HTTP 403 with `api_key_revoked` instead of a generic invalid-key response.
- Improved quota error clarity with additive `details.quota_type`, `details.limit`, and `details.openai_code_alias`.
- Improved external C# example error handling with request ID and structured gateway exception metadata.

### Security
- API key and usage polish preserves public/internal credential separation.
- Public errors remain sanitized and do not expose provider secrets, internal admin tokens, stack traces, raw provider responses, or hidden prompts.

## [1.3.0] - Unreleased

### Added
- Added provider-style OpenAI-compatible integration documentation for external projects in `docs/OPENAI_COMPATIBLE_PROVIDER.md`.
- Added clearer external integration examples for curl, JavaScript, and C# ASP.NET Core clients (`examples/csharp/NestyAiChatService.cs`).

### Changed
- Improved OpenAI-compatible public API behavior for external provider-style integrations.
- Improved `/v1/models`, `/v1/chat/completions`, streaming, API key, quota, and model allowlist compatibility where needed.
- Standardized public error responses toward OpenAI-style error envelopes with `error.type` and `error.param` while preserving existing `error.code` values and `error.details`.
- Added `created` to model list entries; `/v1/models` filters to API key allowlist when a restricted key is authenticated.

### Security
- Public integration polish preserves separation between external API keys and internal admin tokens.
- Error responses remain sanitized and do not expose provider secrets, internal prompts, hidden system messages, stack traces, or raw provider responses.

## [1.2.4] - 2026-06-10

### Added
- Added safe, additive orchestration metadata fields to response: `evidence_sources_used`, `planner_metadata_used`, `retrieval_metadata_used`, `quality_guard_applied`, `pro_context_budget_chars`, and `pro_context_truncated`.
- Integrated dynamic safety guidelines into role prompts based on planner decisions (e.g. clarification needed, memory context sufficient, search planned but not used).

### Changed
- Optimised context handoff for orchestrator roles: Planner receives compact context source list, Critic receives candidate draft and verification checklist, Researcher receives full context, and Finalizer receives size-capped planner/critic notes and candidate draft answer.

## [1.2.3] - 2026-06-10

### Added
- Added safe planner metadata for search and tool decisions, including additive clarification signals.

### Changed
- Improved conservative search and tool planning for current-information requests, memory-like follow-ups, and deterministic tools.
- Added explicit distinction between planned search and search that was actually used in response metadata.

### Security
- Planner metadata remains sanitized and does not expose hidden prompts, chain-of-thought, raw tool payloads, provider secrets, or internal exceptions.

## [1.2.2] - Unreleased

### Added
- Added conservative answer quality guard metadata for empty-answer fallback handling and explicit first-person search-claim detection.
- Mirrored safe `answer_quality` metadata alongside existing response metadata without changing the chat contract shape.

### Fixed
- Replaced empty or whitespace-only non-stream assistant output with a safe fallback message after existing safety cleanup.
- Kept streaming behavior stable by attaching answer-quality metadata only to the final metadata event.

## [1.2.1] - Unreleased

### Fixed
- Ensured diagnostics and provider health checks rebuild cached runtime router/orchestrator objects after model config PATCH and reset operations.
- Added safe top-level provider health metadata for `config_source` and `config_revision` without exposing raw payloads.

## [1.1.1] - Unreleased

### Added
- Added internal admin API key management endpoints for creating, listing, inspecting, and revoking Gateway API keys.

### Security
- Raw API keys are returned only once on creation and are never stored or returned by list/detail endpoints.

## [1.1.0] - Unreleased

### Added
- Added Ollama Cloud provider integration for provider chains and diagnostics.
- Added Ollama Cloud environment configuration.

### Fixed
- Fixed provider-chain fallback behavior so runtime model config fallback entries are attempted when earlier providers/models fail.

### Changed
- Refreshed default provider chains for Flash, Combined, Pro, and embeddings.
- Provider diagnostics and benchmark scripts can include ollama_cloud where configured.

### Security
- Ollama API keys are never logged or exposed in responses.

## [1.0.5] - Unreleased

### Fixed
- Prevented `nesty-pro-1.0` from leaking raw internal tool-call markup in final assistant responses.
- Ensured diagnostics checks use effective runtime model config (default + active override) consistently.

### Added
- Added internal admin diagnostics cleanup endpoint: `DELETE /internal/diagnostics/provider-health`.
- Added safe diagnostics metadata fields for config source/revision and provider/model failure classification.
- Added output safety metadata: `output_safety.internal_tool_markup_removed`.

### Security
- Internal tool-call markup, hidden role notes, hidden prompts, and raw provider error details remain hidden from client-visible responses and diagnostics metadata.

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
