# NestyAI Checkpoint - Phase 4 (Auth, Rate Limit, Usage)

Updated at: 2026-05-29 (Asia/Bangkok)  
Workspace: `D:\NestyAI\nesty-ai`

## 1) Current Verified State

- Project is running with:
  - FastAPI gateway
  - `/`, `/health`, `/v1/models`, `/v1/chat/completions`
  - model aliases + provider fallback
  - guards (input/output/context)
  - web search + tools + planner + cache
- Test suite status:
  - `python -m pytest -q`
  - Result: **64 passed**, 2 warnings

## 2) Important Environment/Repo Notes

- No `.git` repository detected in `D:\NestyAI` or `D:\NestyAI\nesty-ai`.
- `.gitignore` has now been created at project root.
- `.env.example` is still at Phase 3.5 state (not yet updated for Phase 4 vars).

## 3) Phase 4 Progress Already Implemented

### Implemented files

- `app/config.py`
  - Added Phase 4 settings:
    - `nesty_db_path`
    - `nesty_api_key_hash_secret`
    - `require_api_key`
    - `public_health`
    - `public_models`
    - `rate_limit_enabled`
    - `rate_limit_requests_per_minute`
    - `safe_debug_auth`
- `app/storage/db.py`
  - SQLite init + connection helpers.
  - Creates tables if not exists:
    - `api_keys`
    - `usage_logs`
- `app/security/api_key.py`
  - API key generate/hash/verify/prefix helpers.
  - Supports HMAC-SHA256 when `NESTY_API_KEY_HASH_SECRET` is set.
- `app/storage/api_keys.py`
  - Create/list/revoke/find key records.
  - `mark_api_key_used`.

## 4) Phase 4 Pending Work (Must Finish)

### Core backend

1. Create `app/storage/usage.py`
   - Insert usage logs.
   - Query daily/monthly usage counts per key.
   - Summary queries for script.

2. Create `app/security/auth.py`
   - `AuthContext` model.
   - Parse API key from:
     - `Authorization: Bearer ...`
     - `X-Nesty-API-Key`
   - Return structured errors:
     - `missing_api_key`
     - `invalid_api_key`

3. Create `app/security/rate_limit.py`
   - In-memory fixed/sliding window per API key (fallback IP if unauthenticated).
   - Return `rate_limit_exceeded` + `Retry-After`.

4. Update `app/main.py`
   - Run `init_db(settings.nesty_db_path)` on startup.

5. Update `app/core/errors.py`
   - Add error codes:
     - `invalid_api_key`
     - `model_not_allowed`
     - `rate_limit_exceeded`
     - `daily_quota_exceeded`
     - `monthly_quota_exceeded`
     - `usage_logging_failed`

6. Update `app/api/chat.py`
   - Integrate conditional auth by `REQUIRE_API_KEY`.
   - Apply rate-limit check.
   - Apply daily/monthly quota checks.
   - Enforce `allowed_models`.
   - Log usage for both success/error when possible.
   - Optional response auth block controlled by `SAFE_DEBUG_AUTH`.

### Scripts

Create:
- `scripts/create_api_key.py`
- `scripts/list_api_keys.py`
- `scripts/revoke_api_key.py`
- `scripts/usage_summary.py`

### Tests

Create:
- `tests/test_api_key_security.py`
- `tests/test_auth_dependency.py`
- `tests/test_rate_limit.py`
- `tests/test_usage_tracking.py`
- `tests/test_quota.py`
- `tests/test_chat_auth_contract.py`

Notes:
- Use temporary SQLite DB in tests.
- Keep all old tests passing.
- No external provider calls.

### Docs/config

1. Update `.env.example` with Phase 4 vars:
   - `NESTY_DB_PATH=data/nesty.db`
   - `NESTY_API_KEY_HASH_SECRET=`
   - `REQUIRE_API_KEY=false`
   - `PUBLIC_HEALTH=true`
   - `PUBLIC_MODELS=true`
   - `RATE_LIMIT_ENABLED=true`
   - `RATE_LIMIT_REQUESTS_PER_MINUTE=60`
   - `SAFE_DEBUG_AUTH=false`

2. Update `README.md`:
   - Auth flow
   - API key scripts usage
   - Rate-limit/quota behavior
   - Deployment recommendations

## 5) Quick Resume Plan (Other Machine)

1. Install deps:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
2. Continue implementing pending files in section 4.
3. Run tests:
   ```bash
   python -m pytest -q
   ```
4. Run app:
   ```bash
   python run.py
   ```

## 6) Suggested Commit Grouping (if git is initialized later)

1. `feat(auth): add sqlite auth storage + api key security + startup db init`
2. `feat(gateway): enforce auth/rate-limit/quota + usage logging`
3. `test(auth): add phase4 auth/rate/usage/quota contract tests`
4. `docs: update readme and env example for phase4`

