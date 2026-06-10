# NestyAI Error Contract Specification

This document details the standard error response shape and categorized list of error codes used by NestyAI.

---

## Standard Error Response Shape

All API errors return a standard JSON structure with HTTP status code matching the error condition (typically 400, 401, 403, 404, 429, or 5xx).

```json
{
  "error": {
    "message": "Rate limit exceeded. Please try again later.",
    "type": "rate_limit_error",
    "param": null,
    "code": "rate_limit_exceeded",
    "details": {
      "retry_after_seconds": 15
    }
  }
}
```

*   `message`: A human-readable description of the error.
*   `type`: OpenAI-style error category (`authentication_error`, `invalid_request_error`, `permission_error`, `rate_limit_error`, `provider_error`, `api_error`).
*   `param`: Optional field name for validation errors; otherwise `null`.
*   `code`: A machine-readable NestyAI error code (stable; preserved for backward compatibility).
*   `details`: Optional Nesty additive payload (e.g. validation issues, retry durations).

---

## Categorized Error Codes

### 1. Request Validation
*   `invalid_request`: The request payload was malformed or violates schema validation constraints (FastAPI `RequestValidationError` fallback).

### 2. Authorization & Keys
*   `missing_api_key`: The required API key was not supplied in headers. (`type`: `authentication_error`)
*   `invalid_api_key`: The supplied API key is unknown or inactive without a revocation timestamp. (`type`: `authentication_error`)
*   `api_key_revoked`: The API key record exists but was revoked. (`type`: `permission_error`, HTTP 403)
*   `model_not_allowed`: The API key used is unauthorized to access the requested model alias. (`type`: `permission_error`)

**Deferred:** `api_key_disabled` is not emitted in v1.3.1 because there is no public disable workflow yet. Inactive keys without `revoked_at` continue to return `invalid_api_key`.

**OpenAI mapping:** Unknown model aliases return HTTP 400 with `invalid_model` (not 404). External clients may treat this as model-not-found.

### 3. Rate Limits & Quotas
*   `rate_limit_exceeded`: Short-window throttling. HTTP 429. Includes `details.retry_after_seconds` and `Retry-After` header. Chat responses may include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` when the in-memory limiter runs.
*   `daily_quota_exceeded`: Daily request quota exhausted. HTTP 429. `details.quota_type` is `"daily"`, `details.limit` is the configured daily cap, and `details.openai_code_alias` is `"quota_exceeded"`.
*   `monthly_quota_exceeded`: Monthly request quota exhausted. HTTP 429. `details.quota_type` is `"monthly"`, `details.limit` is the configured monthly cap, and `details.openai_code_alias` is `"quota_exceeded"`.

### 4. Provider Routing & Failures
*   `invalid_model`: The requested model alias is unrecognized.
*   `provider_unavailable`: An external API provider returned an error, timed out, or had credentials misconfigured.
*   `all_providers_failed`: All fallback providers configured for the requested route failed to respond.
*   `streaming_not_implemented`: Streaming was requested, but the provider backend does not implement it.
*   `streaming_not_supported`: Streaming was requested, but the provider backend does not support SSE.
*   `stream_interrupted`: The active SSE stream connection was unexpectedly dropped or severed by the provider.
*   `stream_provider_failed`: Standard fallback error for general failures during streaming.

### 5. Search & Tools
*   `invalid_search_mode`: Invalid `search` mode value supplied (must be one of: `"auto"`, `"on"`, `"off"`).
*   `search_failed`: The search query process failed.
*   `invalid_tools_mode`: Invalid `tools` mode value supplied (must be `"auto"`, `"off"`, or list of names).
*   `unknown_tool`: The tool requested is not present in the gateway's tool registry.
*   `tool_execution_failed`: An error occurred during tool execution runtime.
*   `tool_timeout`: The tool exceeded its execution time limit.
*   `tool_not_configured`: Tool credentials or prerequisite environment settings are missing.
*   `unsafe_url_blocked`: A tool attempted to request a URL that was flagged by safety guards.
*   `fetch_failed`: Web query or scraping tool was unable to retrieve a resource.

### 6. Conversations & History
*   `conversation_not_found`: The requested conversation was not found or is archived.
*   `conversation_access_denied`: The conversation belongs to a different API key.
*   `conversation_storage_failed`: An error occurred when persisting messages or updates to SQLite.
*   `invalid_conversation_request`: Invalid parameters supplied (e.g. pagination offsets or invalid query filters).

### 7. Summarization
*   `conversation_summary_failed`: Summarization strategy failed during LLM call.
*   `invalid_summary_mode`: Invalid `summary` mode value supplied (must be `"auto"`, `"off"`, `"force"`).

### 8. Semantic Recall & Memories
*   `invalid_semantic_recall_mode`: Invalid `semantic_recall` mode value (must be `"auto"`, `"on"`, `"off"`).
*   `semantic_recall_failed`: The semantic recall search operation failed.
*   `semantic_recall_unavailable`: Semantic recall was requested but the feature is disabled in server configurations.
*   `invalid_memory_control_request`: Memory control requested cannot be satisfied (e.g. pinning and excluding a message simultaneously).
*   `memory_control_update_failed`: Failed to write memory control edits to SQLite.

### 9. Embeddings
*   `embedding_provider_unavailable`: The configured vector embedder failed to respond.
*   `embedding_generation_failed`: Generation of text embeddings failed.
*   `embedding_storage_failed`: Storing the embedding record failed.

### 10. Security Guards
*   `context_sanitization_failed`: Safety scanning flagged excessive prompt injection patterns in external contexts.

### 11. Internal Admin Endpoints
*   `internal_admin_disabled`: Accessing admin paths when `INTERNAL_ADMIN_ENABLED=false`. Returns HTTP 404.
*   `internal_admin_unauthorized`: Invalid admin token or Authorization header format. Returns HTTP 401.
*   `model_config_not_found`: Config profile is not present in SQLite database.
*   `model_config_invalid`: The config schema is invalid.
*   `model_config_update_failed`: Failed to write model config overrides.
*   `model_config_test_failed`: Provider test verification returned errors.
*   `diagnostics_disabled`: Attempting to use diagnostics endpoints when disabled.
*   `provider_auth_failed`: Diagnostics provider check failed due to auth/credential issue (401/403).
*   `provider_model_unavailable`: Diagnostics provider check could not find requested model (404).
*   `rate_limited`: Diagnostics provider check hit upstream rate limit (429).
*   `provider_timeout`: Diagnostics provider check timed out.
*   `api_key_not_found`: The requested API key was not found.
*   `api_key_create_failed`: The API key creation failed.
*   `api_key_revoke_failed`: The API key revocation failed.
*   `invalid_api_key_request`: The API key management request parameters were invalid.

