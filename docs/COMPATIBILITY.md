# NestyAI API Compatibility Contract

> **Version**: 1.0.0  
> **API Version**: v1  
> **Effective From**: 2025-05  
> **Status**: Compatibility Freeze – v1 public surface is stable.

---

## 1. Stability Guarantee

All endpoints listed under the **v1 Stable** section below are considered **backward-compatible** for the lifetime of the `v1` API prefix.

Changes that will **never** be made to stable endpoints without a major version bump:

- Removing an existing JSON field from a response.
- Changing the type or meaning of an existing JSON field.
- Removing an HTTP endpoint or method.
- Changing the semantics of an existing error code.
- Making a previously optional request field required.

Changes that are **always allowed** without a version bump:

- Adding new optional fields to response objects.
- Adding new optional request parameters.
- Adding new endpoints.
- Improving error messages (text only, not `code`).
- Performance improvements with no semantic change.

---

## 2. v1 Stable Endpoints

### Chat Completions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completions (streaming and non-streaming) |

**Guaranteed response fields** (`ChatCompletionResponse`):

| Field | Type | Notes |
|-------|------|-------|
| `id` | `string` | Unique completion ID |
| `object` | `string` | Always `"chat.completion"` |
| `created` | `integer` | Unix timestamp |
| `model` | `string` | Resolved model identifier (OpenAI-compatible, stable) |
| `choices` | `array` | List of completion choices |
| `choices[].index` | `integer` | Choice index |
| `choices[].message` | `object` | `{role, content}` |
| `choices[].finish_reason` | `string` | e.g. `"stop"` |
| `usage` | `object` | `{prompt_tokens, completion_tokens, total_tokens}` |

**Additive fields** (present but not guaranteed stable across minor releases):

| Field | Notes |
|-------|-------|
| `model_alias` | Human-friendly alias used to select this model |
| `system_fingerprint` | Optional fingerprint |
| `orchestration` | Optional multi-model orchestration metadata (additive since v1.0.4) |

### Models

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/models` | List available model aliases |

**Guaranteed response fields** (each item in `data`):

| Field | Type |
|-------|------|
| `id` | `string` |
| `object` | `string` — always `"model"` |
| `created` | `integer` |
| `owned_by` | `string` |

### Health & Readiness

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | Readiness check (validates DB) |

**Guaranteed response fields**:

| Field | `/health` | `/ready` |
|-------|-----------|----------|
| `status` | `"ok"` | `"ready"` |
| `service` | `"nesty-ai"` | `"nesty-ai"` |
| `version` | release tag | release tag |
| `api_version` | `"v1"` | `"v1"` |
| `database` | — | `"ok"` |

### Conversations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/conversations` | List conversations (paginated) |
| `GET` | `/v1/conversations/{id}` | Get conversation details |
| `DELETE` | `/v1/conversations/{id}` | Delete a conversation |
| `GET` | `/v1/conversations/{id}/messages` | List messages (paginated) |
| `GET` | `/v1/conversations/{id}/export` | Export conversation |
| `POST` | `/v1/conversations/search` | Full-text / semantic search |

---

## 3. Error Shape

All errors follow the envelope:

```json
{
  "error": {
    "code": "<machine_code>",
    "message": "<human_readable>",
    "type": "api_error",
    "details": {}
  }
}
```

Stable error codes: `invalid_request`, `authentication_failed`, `rate_limited`,
`quota_exceeded`, `content_policy_violation`, `provider_unavailable`,
`model_not_found`, `context_too_long`.

See [`ERRORS.md`](ERRORS.md) for the full catalog.

---

## 4. Response Headers

| Header | Description |
|--------|-------------|
| `X-Nesty-API-Version` | Server release version (e.g. `1.0.0`) |
| `X-Content-Type-Options` | Always `nosniff` |
| `X-Frame-Options` | Always `DENY` |

---

## 5. Internal / Admin Endpoints

Endpoints under `/internal/` are **server-to-server only** and carry **no stability guarantee**.  
They may change at any time without notice and must not be called by external clients.

---

## 6. Versioning Policy

- Current stable prefix: **`/v1/`**  
- A `v2` prefix will be introduced only if breaking changes are required.  
- Both prefixes will coexist for a minimum of **6 months** after a new major version is released.  
- Deprecation notices will appear in `CHANGELOG.md` at least one minor release before removal.

---

## 7. Changelog Reference

See [`../CHANGELOG.md`](../CHANGELOG.md) for a full history of API changes.
