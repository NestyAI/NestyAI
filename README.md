# NestyAI (Phase 3.5: Tool Reliability + TTL Cache + Real Weather/Exchange)

NestyAI is a personal FastAPI AI Gateway with OpenAI-compatible chat, provider fallback routing, safety guards, web search, and a server-side tool system.

## Core Endpoints

- `GET /`
- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`

## Model Aliases

- `nesty-flash-1.0`
- `nesty-combined-1.0`
- `nesty-pro-1.0`

## Tool System Overview

- Central `ToolRegistry`
- Rule-based `ToolPlanner`
- Tools selected server-side only
- Tool outputs sanitized by `ContextGuard` as untrusted external context
- `tools` request mode:
  - `"auto"`
  - `"off"`
  - `list[str]`

Supported tools:

- `calculator`
- `wikipedia_lookup`
- `package_version_lookup`
- `weather_lookup` (Open-Meteo)
- `exchange_rate` (Frankfurter)

## Phase 3.5 Cache Overview

NestyAI now includes in-memory TTL cache for tool/search reliability.

- In-memory only
- No Redis yet
- Cache resets on server restart

Default TTL policy:

| Tool/Search | Cache | TTL |
|---|---|---|
| calculator | disabled | - |
| wikipedia_lookup | enabled | 86400s |
| package_version_lookup | enabled | 1800s |
| weather_lookup | enabled | 600s |
| exchange_rate | enabled | 1800s |
| web_search | enabled | 600s |

## Tools vs Search

- `search` controls web search context (`auto/on/off`).
- `tools` controls tool execution (`auto/off/list`).
- They are independent and may both run in one request.

## Request Examples

### tools auto + search auto

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "What is the latest version of fastapi?"}],
    "search": "auto",
    "tools": "auto"
  }'
```

### tools off

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "Viết một đoạn giới thiệu ngắn về NestyAI"}],
    "search": "off",
    "tools": "off"
  }'
```

### tools explicit list

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nesty-combined-1.0",
    "messages": [{"role": "user", "content": "calculate (12500 * 0.15) + 200"}],
    "search": "off",
    "tools": ["calculator"]
  }'
```

### Weather example

- `thời tiết ở TP.HCM hôm nay`
- `weather in Hanoi today`

### Exchange rate examples

- `đổi 100 USD sang VND`
- `What is the current exchange rate from EUR to USD?`

## Provider Notes

- Weather uses Open-Meteo geocoding + forecast APIs.
- Exchange rate uses Frankfurter latest endpoint.
- Both are timeout-protected and return safe failure metadata without crashing chat in auto mode.

## Setup

1. Create Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and set provider keys:

- `GROQ_API_KEY`
- `OPENROUTER_API_KEY`
- `NVIDIA_API_KEY` (optional unless NVIDIA route is used)
- `NVIDIA_BASE_URL` (optional)

## Run

```bash
python run.py
```

## Run Tests

```bash
python -m pytest
```

Notes:

- Tests mock external HTTP calls.
- Tests do not call real Groq/OpenRouter/NVIDIA providers.
- Tests do not call real DuckDuckGo/Wikipedia/Open-Meteo/Frankfurter/PyPI/npm.

## Smoke Test

```bash
python scripts/smoke_test.py
```

Optional custom URL:

```bash
BASE_URL=http://127.0.0.1:8000 python scripts/smoke_test.py
```

## Tool Demo Script

```bash
python scripts/test_tools.py
```

## Troubleshooting

- `missing_api_key`: set provider API keys in `.env`.
- `invalid_tools_mode`: `tools` must be `"auto"`, `"off"`, or `list[str]`.
- `unknown_tool`: explicit `tools` list contains unsupported tool name.
- `search_failed` with `search=on`: search backend temporarily unavailable.
- Weather/exchange API temporary failure: retry later or fallback to non-live answer.

