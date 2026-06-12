# NestyAI Gateway — OpenAI-Compatible Provider Integration

NestyAI Gateway is a **provider-grade OpenAI-compatible AI gateway**. External applications (DeskMart, KotNest, NestyChat, and future apps) can integrate the same way they would integrate OpenAI, OpenRouter, Groq, or Together:

- **Base URL** — `https://gateway.example.com/v1`
- **API key** — `nsk_dev_...` or `nsk_live_...`
- **Model name** — `nesty-flash-1.0`, `nesty-combined-1.0`, or `nesty-pro-1.0`

Gateway owns routing, fallback, streaming, quotas, and safe metadata. Your app owns system prompts, domain context, catalog data, business rules, and UI.

---

## Recommended architecture

```
External app backend  →  NestyAI Gateway  →  upstream providers
Browser / mobile UI   →  your backend only (never Gateway with API key)
```

**Do not call Gateway directly from a browser with an API key.** API keys must stay on your server. CORS may be enabled for development, but production integrations should be **server-to-server**.

Never use the internal admin token (`NESTY_INTERNAL_ADMIN_TOKEN`) in external projects. It is for Nesty Console / operator tooling only.

---

## Authentication

```http
Authorization: Bearer nsk_xxx
Content-Type: application/json
```

Alternative header (supported): `X-Nesty-API-Key: nsk_xxx`

---

## Public model aliases

| Alias | Profile |
|-------|---------|
| `nesty-flash-1.0` | Fast, lightweight |
| `nesty-combined-1.0` | Balanced default |
| `nesty-pro-1.0` | Highest quality |

Aliases remain stable when provider chains change behind the scenes.

---

## GET /v1/models

List models available to the caller.

```bash
curl -s "https://gateway.example.com/v1/models" \
  -H "Authorization: Bearer nsk_xxx"
```

**Response shape (OpenAI-compatible core + additive fields):**

```json
{
  "object": "list",
  "data": [
    {
      "id": "nesty-combined-1.0",
      "object": "model",
      "created": 0,
      "owned_by": "nestyai",
      "description": "Balanced default profile"
    }
  ]
}
```

**Allowlist behavior:**

- If your API key has **no model allowlist**, all public models are listed.
- If your API key is **restricted to specific models**, only those models appear.
- `POST /v1/chat/completions` always enforces the allowlist independently.

Unauthenticated listing remains available when your Gateway config allows it (`PUBLIC_MODELS=true` by default).

---

## POST /v1/chat/completions

### Non-streaming

```bash
curl -s "https://gateway.example.com/v1/chat/completions" \
  -H "Authorization: Bearer nsk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [
      {"role": "system", "content": "You are an AI assistant inside an external app."},
      {"role": "user", "content": "Hello"}
    ],
    "stream": false
  }'
```

**Core response fields:**

```json
{
  "id": "chatcmpl_...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "nesty-combined-1.0",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

Gateway adds **safe additive metadata** (`guard`, `tools`, `sources`, `orchestration`, `planner`, `retrieval`, etc.). Simple OpenAI clients can ignore these fields.

### Streaming (SSE)

```bash
curl -N "https://gateway.example.com/v1/chat/completions" \
  -H "Authorization: Bearer nsk_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

Events:

1. `object: "chat.completion.chunk"` with `choices[].delta.content`
2. Optional `object: "chat.completion.metadata"` (additive Nesty fields)
3. `data: [DONE]`

Clients that only read `choices[].delta.content` continue to work.

---

## OpenAI SDK compatibility

Many OpenAI SDKs accept a custom base URL:

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://gateway.example.com/v1",
  apiKey: process.env.NESTY_API_KEY,
});

const completion = await client.chat.completions.create({
  model: "nesty-combined-1.0",
  messages: [{ role: "user", content: "Hello" }],
});
```

Harmless OpenAI request fields (`user`, `top_p`, `stop`, `metadata`, etc.) are accepted and ignored when not supported. Nesty-specific optional fields (`search`, `tools`, `store`, `semantic_recall`, `conversation_id`) remain available but are not required.

---

## Error response format

All errors use a consistent envelope:

```json
{
  "error": {
    "message": "Human-readable safe message.",
    "type": "authentication_error",
    "param": null,
    "code": "invalid_api_key",
    "details": {}
  }
}
```

| HTTP | `type` | Example `code` |
|------|--------|----------------|
| 400 | `invalid_request_error` | `invalid_request`, `invalid_model` |
| 401 | `authentication_error` | `missing_api_key`, `invalid_api_key` |
| 403 | `permission_error` | `model_not_allowed`, `api_key_revoked` |
| 429 | `rate_limit_error` | `rate_limit_exceeded`, `daily_quota_exceeded`, `monthly_quota_exceeded` |
| 502/503 | `provider_error` | `provider_unavailable`, `all_providers_failed` |
| 500 | `api_error` | `internal_server_error` |

**OpenAI mapping note:** Unknown model aliases return HTTP **400** with code **`invalid_model`**. This is equivalent to OpenAI-style “model not found” for external clients even though the HTTP status differs from OpenAI’s 404.

The `details` object is a Nesty additive field for structured context (e.g. `retry_after_seconds`, `quota_type`, `limit`, `openai_code_alias`, `request_id`). Errors never include stack traces, provider API keys, admin tokens, hidden prompts, or raw provider response bodies.

### Response headers for troubleshooting

| Header | When |
|--------|------|
| `X-Request-ID` | Every public response; echo safe client value or generate `req_...` |
| `X-RateLimit-Limit` | Chat route when rate limiting is enabled |
| `X-RateLimit-Remaining` | Chat route when rate limiting is enabled |
| `X-RateLimit-Reset` | Chat route when rate limiting is enabled |
| `Retry-After` | HTTP 429 rate-limit responses |

---

## Troubleshooting external integrations

Log these fields from your **server-side** app when a Gateway call fails:

- HTTP status code
- `error.code`
- `error.type`
- `X-Request-ID` response header
- requested model alias

**Never log** the API key, `Authorization` header, or internal admin token.

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| 401 `missing_api_key` | No Bearer key sent | Set `Authorization: Bearer nsk_...` on server-side requests |
| 401 `invalid_api_key` | Wrong or unknown key | Verify key value and environment; key was never issued or hash mismatch |
| 403 `api_key_revoked` | Key was revoked | Create a new key in Nesty Console / internal admin |
| 403 `model_not_allowed` | Key allowlist excludes model | Use an allowed alias or update key allowlist |
| 400 `invalid_model` | Unknown model alias | Use `nesty-flash-1.0`, `nesty-combined-1.0`, or `nesty-pro-1.0` |
| 429 `rate_limit_exceeded` | Short-window throttling | Back off using `Retry-After` / `details.retry_after_seconds` |
| 429 `daily_quota_exceeded` / `monthly_quota_exceeded` | Quota exhausted | Check `details.quota_type` and `details.limit`; treat as quota exhaustion (`openai_code_alias: quota_exceeded`) |
| 502/503 provider errors | Upstream provider failure | Retry with backoff; log `X-Request-ID` for operator support |
| Stream closes early | Network/proxy timeout or provider failure | Confirm server-side streaming client; inspect final error JSON if returned before SSE |
| Browser call fails / key exposed | Client-side integration anti-pattern | Call Gateway only from your backend, never from browser JavaScript |
| Wrong URL / 404 | Base URL misconfiguration | Base URL must include `/v1`; POST path is `/v1/chat/completions` or relative `chat/completions` when `BaseAddress` ends with `/v1/` |
| CORS errors | Browser direct call | Move integration to server-side; CORS is not a substitute for secure key handling |
| ASP.NET `BaseAddress` mistakes | Double `/v1` or missing `/v1` | Set `BaseUrl` to `https://gateway.example.com/v1` and `BaseAddress` to that value with trailing slash |

**Deferred:** `api_key_disabled` is not emitted until a public disable workflow exists. Other inactive keys without `revoked_at` continue to return `invalid_api_key`.

---

## API key setup

Create one key per external project and environment via internal admin (Nesty Console):

| Name | Use |
|------|-----|
| `deskmart-dev` | Development |
| `deskmart-prod` | Production |
| `kotnest-prod` | Production |

Restrict `allowed_models` and set daily/monthly quotas as needed.

---

## JavaScript fetch (server-side)

```javascript
const response = await fetch("https://gateway.example.com/v1/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${process.env.NESTY_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "nesty-combined-1.0",
    messages: [{ role: "user", content: "Hello" }],
    stream: false,
  }),
});

const data = await response.json();
if (!response.ok) {
  throw new Error(data.error?.message ?? "Gateway request failed");
}
console.log(data.choices[0].message.content);
```

---

## C# ASP.NET Core (server-side only)

**appsettings.json:**

```json
{
  "NestyAI": {
    "BaseUrl": "https://gateway.example.com/v1",
    "ApiKey": "nsk_xxx",
    "DefaultModel": "nesty-combined-1.0"
  }
}
```

**NestyAiOptions.cs:**

```csharp
public sealed class NestyAiOptions
{
    public const string SectionName = "NestyAI";
    public string BaseUrl { get; set; } = "";
    public string ApiKey { get; set; } = "";
    public string DefaultModel { get; set; } = "nesty-combined-1.0";
}
```

**NestyAiChatService.cs** — see [`examples/csharp/NestyAiChatService.cs`](../examples/csharp/NestyAiChatService.cs).

Register in `Program.cs`:

```csharp
builder.Services.Configure<NestyAiOptions>(
    builder.Configuration.GetSection(NestyAiOptions.SectionName));
builder.Services.AddHttpClient<INestyAiChatService, NestyAiChatService>();
```

**Important:** Keep `ApiKey` in server configuration or a secret manager. Never embed it in Razor views, Blazor WASM, or browser JavaScript.

---

## Runtime OpenAI-compatible providers (Gateway v1.5.1+)

Operators can register additional OpenAI-compatible upstreams at runtime via `/internal/console/runtime/providers/openai-compatible` (Internal Admin Token required). These providers:

- Use the same OpenAI chat-completions request/response shape as built-in adapters.
- Route through existing fallback when referenced in a model `provider_chain`.
- Are **not** a generic plugin system — proprietary or non-OpenAI APIs still need built-in adapter code.

Local/private provider URLs (LM Studio, Ollama on localhost, etc.) are **blocked by default**. Enabling `NESTY_RUNTIME_PROVIDER_ALLOW_PRIVATE_BASE_URL` is self-host/dev mode and can be dangerous if misconfigured. See [`RUNTIME_CONFIG.md`](RUNTIME_CONFIG.md).

---

## Related documentation

- [`API_CONTRACT.md`](API_CONTRACT.md) — full endpoint specification
- [`COMPATIBILITY.md`](COMPATIBILITY.md) — v1 stability guarantees
- [`ERRORS.md`](ERRORS.md) — error code catalog
- [`openapi.json`](openapi.json) — machine-readable schema
