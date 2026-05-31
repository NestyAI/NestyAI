# Pre-Release Checklist

Use this checklist to verify the stability, security, and setup readiness of NestyAI before tag and release.

- [ ] **Run Full Test Suite**
  - Command: `python -m pytest -q`
  - Ensure all 390+ unit and integration tests pass successfully.

- [ ] **Run Project Doctor Script**
  - Command: `python scripts/doctor.py`
  - Ensure all critical checks pass and warnings are reviewed.

- [ ] **Verify Environment Template (`.env.example`)**
  - Ensure no actual secrets (API keys, admin tokens) are committed in the repository or template file.
  - Review that all environment variables have default descriptions or safe defaults.

- [ ] **Verify Docker Build**
  - Command: `docker compose build` or `docker build -t nesty-ai:latest .`
  - Confirm the image builds successfully without warnings or packaging failures.

- [ ] **Secret Hygiene Audit**
  - Check for any accidental hardcoded keys or hash secrets in git history (`git diff` or pre-commit hooks).
  - Confirm `CLOUDFLARE_TUNNEL_TOKEN` is not committed.
  - Confirm `.env` is not committed.
  - Confirm `.cloudflared/` and `cloudflare/.log` / `cloudflare/.pid` runtime artifacts are ignored.

- [ ] **Verify Base and Health Endpoints**
  - Start the app: `python run.py`
  - Query health checks: `curl http://127.0.0.1:8000/health` (should return 200 OK with `version` and `api_version` fields).
  - Query ready checks: `curl http://127.0.0.1:8000/ready` (should return 200 OK).
  - Verify `X-Nesty-API-Version` header is present in all responses.
  - If using Cloudflare Tunnel, verify `/health` and `/ready` through the public tunnel URL.

- [ ] **Verify Tunnel Host Security Settings (When Browser Clients Use Tunnel URL)**
  - Confirm `CORS_ALLOW_ORIGINS` uses exact frontend origin(s), not `*`.
  - Confirm `TRUSTED_HOSTS` includes the public tunnel hostname/domain when TrustedHostMiddleware is enabled.
  - Confirm internal admin token is never exposed to frontend/mobile clients.

- [ ] **Verify API Key Management**
  - Run the key generator: `python scripts/create_api_key.py --name test-key --env dev`
  - Verify that the prefix and generated key are displayed and saved to SQLite database correctly.

- [ ] **Verify Chat Completion (Non-Streaming)**
  - Send a simple POST request to `/v1/chat/completions` using a generated key and confirm response format matches OpenAI specs.

- [ ] **Verify Chat Completion (Streaming)**
  - Send a POST request with `"stream": true` to `/v1/chat/completions` and verify SSE chunks are generated and terminate with `data: [DONE]`.

- [ ] **Verify Provider Diagnostics**
  - Run diagnostics: `python scripts/benchmark_provider_chains.py --include-roles --dry-run`
  - Confirm provider paths can be resolved and simulated health check processes succeed.

- [ ] **Backup Database Before Upgrades**
  - Back up `data/nesty.db` before applying migrations or upgrading local databases in case rollback is needed.

- [ ] **Verify API Contracts & Error Guidelines**
  - Verify that the endpoints strictly conform to the spec in `docs/API_CONTRACT.md`.
  - Confirm error response formats and error codes align with `docs/ERRORS.md`.
  - Review compatibility guarantees in `docs/COMPATIBILITY.md`.

- [ ] **Verify OpenAPI Export**
  - Run the OpenAPI exporter script: `python scripts/export_openapi.py`
  - Confirm `docs/openapi.json` is generated successfully without error.
  - Run the check mode: `python scripts/export_openapi.py --check` — must exit 0.

- [ ] **Update `app/version.py` VERSION**
  - Bump `VERSION` from `1.0.0-rc1` to the final release version (e.g. `1.0.0`).
  - Re-run export_openapi.py to regenerate docs/openapi.json.

- [ ] **Smoke Test Client Examples**
  - Run non-streaming example: `python examples/python/chat_non_stream.py`
  - Run streaming example: `python examples/python/chat_stream.py`
  - Ensure both retrieve valid mock responses from the local server.

- [ ] **Tag Release**
  - Tag the release version: `git tag -a vX.Y.Z -m "Release version X.Y.Z"`
  - Push tags: `git push origin vX.Y.Z`
