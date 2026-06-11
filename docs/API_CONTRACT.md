# NestyAI API Contract Specification

This document details the public and internal API contracts for NestyAI.

---

## Public Endpoints

Public endpoints represent the core API interface intended for clients (e.g., CLI, Nesty Console, NestyChat Web, and Android clients).

### 1. Root Endpoint
*   **Method**: `GET`
*   **Path**: `/`
*   **Description**: Returns basic service metadata.
*   **Auth**: None required.
*   **Response (200 OK)**:
    ```json
    {
      "name": "NestyAI",
      "version": "0.1.0",
      "description": "Personal AI Gateway Server"
    }
    ```

### 2. Service Health
*   **Method**: `GET`
*   **Path**: `/health`
*   **Description**: Service level health check.
*   **Auth**: Optional (Required if `REQUIRE_API_KEY=true` and `PUBLIC_HEALTH=false`).
*   **Response (200 OK)**:
    ```json
    {
      "status": "ok",
      "service": "nesty-ai",
      "version": "0.1.0"
    }
    ```

### 3. Readiness check
*   **Method**: `GET`
*   **Path**: `/ready`
*   **Description**: Readiness health check verifying database connectivity.
*   **Auth**: Optional (Required if `REQUIRE_API_KEY=true` and `PUBLIC_HEALTH=false`).
*   **Response (200 OK)**:
    ```json
    {
      "status": "ready",
      "service": "nesty-ai",
      "database": "ok"
    }
    ```
*   **Response (503 Service Unavailable)**:
    ```json
    {
      "error": {
        "code": "provider_unavailable",
        "message": "Service is not ready.",
        "type": "api_error",
        "details": {
          "database": "error"
        }
      }
    }
    ```

### 4. List Models
*   **Method**: `GET`
*   **Path**: `/v1/models`
*   **Description**: Lists all active model profiles and model aliases.
*   **Auth**: Optional (Required if `REQUIRE_API_KEY=true` and `PUBLIC_MODELS=false`).
*   **Response (200 OK)**:
    ```json
    {
      "object": "list",
      "data": [
        {
          "id": "nesty-flash-1.0",
          "object": "model",
          "owned_by": "nestyai",
          "description": "Fast and cheap model alias",
          "config_source": "default"
        }
      ]
    }
    ```

### 5. Chat Completions
*   **Method**: `POST`
*   **Path**: `/v1/chat/completions`
*   **Description**: Creates a model response for a given chat conversation.
*   **Auth**: Bearer API Key required if `REQUIRE_API_KEY=true`.
*   **Request Payload**:
    ```json
    {
      "model": "nesty-combined-1.0",
      "messages": [
        {
          "role": "user",
          "content": "Hello!"
        }
      ],
      "temperature": 0.7,
      "max_tokens": 1024,
      "stream": false,
      "search": "auto",
      "tools": "auto",
      "orchestration": "auto",
      "semantic_recall": "auto",
      "conversation_id": "conv_123",
      "store": true,
      "summary": "auto"
    }
    ```
    *   **Allowed Values**:
        *   `search`: `"auto"`, `"on"`, `"off"`
        *   `tools`: `"auto"`, `"off"`, or `list[str]` (e.g. `["current_datetime", "web_search"]`)
        *   `orchestration`: `"auto"`, `"off"`, `"force"`
        *   `semantic_recall`: `"auto"`, `"on"`, `"off"`
        *   `summary`: `"auto"`, `"off"`, `"force"`
*   **Response (200 OK) Non-Streaming**:
    ```json
    {
      "id": "chatcmpl_abc123",
      "object": "chat.completion",
      "created": 1672531199,
      "model": "nesty-combined-1.0",
      "provider": "groq",
      "choices": [
        {
          "index": 0,
          "message": {
            "role": "assistant",
            "content": "Hello! How can I help you today?"
          },
          "finish_reason": "stop"
        }
      ],
      "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 8,
        "total_tokens": 18
      },
      "guard": {
        "input_redacted": false,
        "output_redacted": false,
        "redaction_count": 0,
        "categories": []
      },
      "tools": {
        "search": {
          "enabled": false,
          "query": null,
          "queries": [],
          "failed": false,
          "results_count": 0,
          "filtered_result_count": null,
          "provider": null,
          "latency_ms": null,
          "error_code": null,
          "cache_hit": false,
          "context_chars": null,
          "decision_reason": null,
          "used": false
        },
        "used": [],
        "executions": []
      },
      "sources": [],
      "orchestration": {
        "enabled": true,
        "requested": "auto",
        "used": false,
        "mode": "single",
        "decision_reason": "simple_request",
        "complexity_score": 0,
        "roles": [],
        "fallback_used": false,
        "internal_calls": 0,
        "role_latency_ms": null,
        "completed_roles": [],
        "failed_roles": [],
        "skipped_roles": ["planner", "researcher", "critic", "finalizer"],
        "fallback_reason": null,
        "streaming_fallback": false,
        "total_latency_ms": null,
        "evidence_sources_used": null,
        "planner_metadata_used": null,
        "retrieval_metadata_used": null,
        "quality_guard_applied": null,
        "pro_context_budget_chars": null,
        "pro_context_truncated": null
      },
      "semantic_recall": {
        "enabled": false,
        "requested": "auto",
        "used": false,
        "reason": "no_matches"
      },
      "provider_health": null,
      "output_safety": {
        "internal_tool_markup_detected": false,
        "internal_tool_markup_removed": false
      },
      "answer_quality": {
        "checked": false,
        "flags": [],
        "action": "none",
        "empty_before_fallback": false,
        "retry_attempted": false,
        "sanitized_empty": false
      },
      "planner": {
        "search_decision": "no_search_needed",
        "search_planned": false,
        "search_used": false,
        "tool_decision": "no_tool_needed",
        "tools_planned": [],
        "tools_used": [],
        "clarification_needed": false
      },
      "retrieval": {
        "context_used": false,
        "search_sources": []
      },
      "lifecycle_events": [
        {
          "type": "chat.request_started",
          "status": "ok"
        }
      ],
      "auth": null,
      "conversation": {
        "id": "conv_123",
        "created": false,
        "summary_mode": "auto",
        "summary_used": false,
        "summary_updated": false
      },
      "model_alias": "nesty-combined-1.0"
    }
    ```
    *   `provider` is selected from the configured provider chain (e.g. `groq`, `openrouter`, `nvidia`, `ollama_cloud`) after fallback resolution.
*   **Response (200 OK) Streaming (`stream=true`)**:
    *   Content-Type: `text/event-stream`
    *   Emits sequential server-sent events:
        *   **Chunk Event**:
            `data: {"id": "...", "object": "chat.completion.chunk", "created": 1234, "model": "...", "provider": "...", "choices": [{"index": 0, "delta": {"content": "part"}, "finish_reason": null}]}`
        *   **Metadata Event**:
            `data: {"id": "...", "object": "chat.completion.metadata", "created": 1234, "model": "...", "provider": "...", "guard": {...}, "tools": {...}, "sources": [...], "usage": {...}, "orchestration": {...}, "semantic_recall": {...}, "provider_health": {...}, "output_safety": {...}, "answer_quality": {...}, "planner": {...}, "retrieval": {...}, "conversation": {...}, "model_alias": "..."}`
        *   **Termination Event**:
            `data: [DONE]`
        *   **Interrupted Stream Error (if interrupted)**:
            `data: {"object": "chat.completion.error", "error": {"code": "stream_interrupted", "message": "The streaming response was interrupted."}}`

### 6. List Conversations
*   **Method**: `GET`
*   **Path**: `/v1/conversations`
*   **Parameters**: `limit` (default 20), `offset` (default 0), `archived` (`"active"`, `"archived"`, `"all"`), `q` (search query)
*   **Response (200 OK)**:
    ```json
    {
      "object": "list",
      "data": [
        {
          "id": "conv_123",
          "title": "NestyAI Introduction",
          "created_at": "2026-05-30T12:00:00Z",
          "updated_at": "2026-05-30T12:05:00Z",
          "archived_at": null,
          "message_count": 2,
          "last_message_at": "2026-05-30T12:05:00Z",
          "summary_exists": false,
          "summary_updated_at": null,
          "summary_message_count": 0
        }
      ]
    }
    ```

### 7. Get Conversation Detail
*   **Method**: `GET`
*   **Path**: `/v1/conversations/{conversation_id}`
*   **Parameters**: `limit` (default 20, limits message list)
*   **Response (200 OK)**:
    ```json
    {
      "conversation": {
        "id": "conv_123",
        "title": "NestyAI Introduction",
        "created_at": "2026-05-30T12:00:00Z",
        "updated_at": "2026-05-30T12:05:00Z",
        "archived_at": null,
        "message_count": 2,
        "last_message_at": "2026-05-30T12:05:00Z",
        "summary_exists": false,
        "summary": null,
        "summary_updated_at": null,
        "summary_message_count": 0
      },
      "messages": [
        {
          "id": "msg_123",
          "role": "user",
          "content": "Hello",
          "model": "nesty-combined-1.0",
          "provider": null,
          "created_at": "2026-05-30T12:00:00Z"
        }
      ]
    }
    ```

### 8. Patch Conversation Title
*   **Method**: `PATCH`
*   **Path**: `/v1/conversations/{conversation_id}`
*   **Request Payload**:
    ```json
    {
      "title": "New Title"
    }
    ```
*   **Response (200 OK)**:
    ```json
    {
      "ok": true
    }
    ```

### 9. Delete/Archive Conversation
*   **Method**: `DELETE`
*   **Path**: `/v1/conversations/{conversation_id}`
*   **Response (200 OK)**:
    ```json
    {
      "ok": true
    }
    ```

### 10. Get Conversation Messages
*   **Method**: `GET`
*   **Path**: `/v1/conversations/{conversation_id}/messages`
*   **Parameters**: `limit` (default 50), `offset` (default 0), `order` (`"asc"` or `"desc"`)
*   **Response (200 OK)**:
    ```json
    {
      "object": "list",
      "conversation_id": "conv_123",
      "data": [...],
      "pagination": {
        "limit": 50,
        "offset": 0,
        "count": 1,
        "has_more": false
      }
    }
    ```

### 11. Search Conversations/Messages (FTS5)
*   **Method**: `GET`
*   **Path**: `/v1/conversations/search`
*   **Parameters**: `q` (query), `limit` (default 20), `offset` (default 0), `scope` (`"all"`, `"conversations"`, `"messages"`), `backend` (`"auto"`, `"fts"`, `"like"`)
*   **Response (200 OK)**:
    ```json
    {
      "object": "conversation.search_results",
      "query": "gateway",
      "conversations": [...],
      "messages": [...],
      "search": {
        "backend": "fts",
        "fallback_used": false,
        "query": "gateway",
        "scope": "all"
      },
      "pagination": {
        "limit": 20,
        "offset": 0,
        "count": 2,
        "has_more": false
      }
    }
    ```

### 12. Summarize Conversation
*   **Method**: `POST`
*   **Path**: `/v1/conversations/{conversation_id}/summarize`
*   **Response (200 OK)**:
    ```json
    {
      "ok": true,
      "summary_updated": true,
      "summary_message_count": 5
    }
    ```

### 13. Clear Messages
*   **Method**: `POST`
*   **Path**: `/v1/conversations/{conversation_id}/clear`
*   **Request Payload**:
    ```json
    {
      "keep_summary": false
    }
    ```
*   **Response (200 OK)**:
    ```json
    {
      "ok": true
    }
    ```

### 14. Reset Summary
*   **Method**: `POST`
*   **Path**: `/v1/conversations/{conversation_id}/reset-summary`
*   **Response (200 OK)**:
    ```json
    {
      "ok": true
    }
    ```

### 15. Export Conversation
*   **Method**: `GET`
*   **Path**: `/v1/conversations/{conversation_id}/export`
*   **Parameters**: `include_metadata` (default true), `messages_order` (`"asc"` or `"desc"`)
*   **Response (200 OK)**:
    ```json
    {
      "id": "conv_123",
      "title": "Intro",
      "created_at": "...",
      "messages": [...]
    }
    ```

### 16. Update Message Memory Controls
*   **Method**: `PATCH`
*   **Path**: `/v1/conversations/{conversation_id}/messages/{message_id}/memory`
*   **Request Payload**:
    ```json
    {
      "pinned": true,
      "excluded": false,
      "tags": ["fact"]
    }
    ```
*   **Response (200 OK)**:
    ```json
    {
      "ok": true,
      "message": {
        "id": "msg_456",
        "memory_pinned": true,
        "memory_excluded": false,
        "memory_tags": ["fact"],
        "memory_updated_at": "2026-05-30T12:05:00Z"
      }
    }
    ```

### 17. Get Memory Controlled Messages
*   **Method**: `GET`
*   **Path**: `/v1/conversations/memory-controls`
*   **Parameters**: `pinned` (bool), `excluded` (bool), `limit` (default 50), `offset` (default 0)
*   **Response (200 OK)**:
    ```json
    {
      "object": "list",
      "data": [...],
      "filters": {
        "pinned": true,
        "excluded": null
      },
      "pagination": {
        "limit": 50,
        "offset": 0,
        "count": 1,
        "has_more": false
      }
    }
    ```

---

## Internal Endpoints

Internal endpoints are hidden administrative routes.
*   **Usage constraint**: Intended for **Server-to-Server** direct use only (e.g. from a secure proxy or next-hop controller path inside future Nesty Console backend routes).
*   **Configuration Requirement**: Requires `INTERNAL_ADMIN_ENABLED=true`.
*   **Security Header**: Must supply `Authorization: Bearer NESTY_INTERNAL_ADMIN_TOKEN`.

### 1. Model Configurations
*   `GET /internal/model-configs`: List configurations
*   `GET /internal/model-configs/{model_id}`: Detail config
*   `POST /internal/model-configs`: Create config
*   `PUT /internal/model-configs/{model_id}`: Update config
*   `DELETE /internal/model-configs/{model_id}`: Delete config
*   `POST /internal/model-configs/test-provider`: Validate external provider credentials

### 2. Embeddings Diagnostics
*   `POST /internal/embeddings/test`: Test embedder output
*   `POST /internal/embeddings/recall-test`: Test semantic memory search retrieval results

### 3. Diagnostics
*   `GET /internal/diagnostics/provider-health`: List historical health records
*   `GET /internal/diagnostics/provider-health/latest`: Get latest target states
*   `DELETE /internal/diagnostics/provider-health`: Clear provider health history (supports optional filters)
*   `GET /internal/diagnostics/provider-health/summary`: Reliability & latency summary metrics
*   `POST /internal/diagnostics/provider-health/check`: Trigger test on alias
*   `POST /internal/diagnostics/provider-model/check`: Trigger direct provider/model check

### 4. API Keys Management
*   `GET /internal/api-keys`: List all API keys (supports environment, revoked, limit, offset, q search filters).
*   `POST /internal/api-keys`: Create an API key (returns the raw API key exactly once in the response).
*   `GET /internal/api-keys/{api_key_id}`: Get detail of an API key (omits secrets/hash).
*   `POST /internal/api-keys/{api_key_id}/revoke`: Idempotently revoke a key (removes usability immediately).
*   `PATCH /internal/api-keys/{api_key_id}`: Update metadata properties of an API key (name, environment, limits, models).
