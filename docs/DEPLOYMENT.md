# Deployment Guide

This guide describes how to deploy NestyAI in development and production environments.

---

## 1. Local Run

To deploy NestyAI locally for development or testing:

1. **Install Python 3.11+**
2. **Clone and Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
3. **Configure Environment**:
   ```bash
   copy .env.example .env
   ```
   Edit `.env` and set at least one provider API key (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `OLLAMA_API_KEY`).
4. **Run Diagnostics**:
   ```bash
   python scripts/doctor.py
   ```
5. **Start App**:
   ```bash
   python run.py
   ```
   The gateway will be available at `http://127.0.0.1:8000`.

---

## 2. Docker Compose (Self-Hosting)

Docker is the recommended approach for hosting NestyAI continuously.

1. **Verify `docker-compose.yml`**:
   The default setup mounts the `data` directory to persist SQLite databases.
2. **Build and Start Container**:
   ```bash
   docker compose up --build -d
   ```
3. **Verify Logs**:
   ```bash
   docker compose logs -f
   ```
4. **Execute CLI Scripts Inside Container**:
   ```bash
   docker compose exec nesty-ai python scripts/create_api_key.py --name my-key
   ```

---

## 3. Cloudflare Tunnel Deployment

Cloudflare Tunnel is optional. It is useful when the Gateway runs on a private host/container but needs a public HTTPS URL. This helps avoid browser mixed-content and cleartext HTTP issues for future Nesty Console / NestyChat Web clients.

Create your tunnel token in the Cloudflare Zero Trust dashboard, then store it only in `.env`, server environment variables, or panel secrets. Never commit the token.

### Mode A: Docker Compose sidecar

This mode runs `cloudflared` as a sidecar using the `cloudflare/cloudflared` image.

Required environment variable:

```env
CLOUDFLARE_TUNNEL_TOKEN=
```

Start:

```bash
docker compose --profile tunnel up -d
```

Logs:

```bash
docker compose logs -f cloudflared
```

If using a split override file approach instead of Compose profiles:

```bash
docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d
```

### Mode B: Pterodactyl / container-panel mode

Use this for managed container environments where `cloudflared` is installed/started inside the same server container as NestyAI.

Recommended environment values:

```env
CLOUDFLARE_TUNNEL_TOKEN=
TUNNEL_AUTO_INSTALL_CLOUDFLARED=1
CLOUDFLARED_BIN_PATH=/home/container/.cloudflared/bin/cloudflared
TUNNEL_ENABLED=1
CLOUDFLARED_LOG_PATH=./cloudflare/cloudflared.log
CLOUDFLARED_PID_PATH=./cloudflare/cloudflared.pid
```

#### Panel startup command (typical egg)

Many hosts lock the startup command to something like:

```bash
if [[ -d .git ]] && [[ "${AUTO_UPDATE}" == "1" ]]; then git pull; fi
if [[ ! -z "${PY_PACKAGES}" ]]; then pip install -U --prefix .local ${PY_PACKAGES}; fi
pip install -U --prefix .local -r ${REQUIREMENTS_FILE}
/usr/local/bin/python /home/container/${PY_FILE} ${APP_ARGS}
```

You usually **cannot** edit that script. You **can** change panel variables such as:

| Variable | Typical label | Recommended value |
| --- | --- | --- |
| `PY_FILE` | *APP PY FILE* | `bootstrap.py` |
| `AUTO_UPDATE` | *AUTO UPDATE* | `1` (keep enabled) |
| `REQUIREMENTS_FILE` | *REQUIREMENTS FILE* | `requirements.txt` |

Set **`PY_FILE=bootstrap.py`** (not `run.py`) for panel deployments that clone from GitHub.

#### Git sync bootstrap (recommended)

When `AUTO UPDATE=1`, panel `git pull` often **fails** if tracked files were modified on the server (for example after a partial merge or manual edit to provider modules). The startup script still continues; NestyAI uses **`bootstrap.py`** to recover before Gateway starts.

Files (tracked in repo):

| File | Role |
| --- | --- |
| `bootstrap.py` | Panel entrypoint — sync git, then exec `run.py` |
| `git_sync.py` | Shared `git fetch` + `git reset --hard origin/<branch>` helper |
| `run.py` | Also calls `git_sync` on start when import succeeds (belt-and-suspenders) |

**First-time panel setup**

1. Clone or install NestyAI into `/home/container/` (egg git repo or manual).
2. Set **`PY_FILE=bootstrap.py`** in the panel.
3. Configure `.env`, tunnel vars, and provider keys as usual.
4. Restart the server.

**Expected log markers**

```
============================================================
NESTYAI BOOTSTRAP — entrypoint active
...
[nesty-git-sync] ok: git fetch origin main
[nesty-git-sync] ok: git reset --hard origin/main
[nesty-git-sync] active commit: <short-sha>
[nesty-bootstrap] exec run.py
```

If you **do not** see `NESTYAI BOOTSTRAP — entrypoint active`, `PY_FILE` is still `run.py` or `bootstrap.py` is missing from `/home/container/`.

**What git sync changes vs preserves**

| Affected | Not affected (runtime data) |
| --- | --- |
| Tracked repo files (`app/`, `config/`, `docs/`, …) | `.env` |
| | `data/` and `data/nesty.db` (runtime providers, model overrides, conversations) |
| | `.nesty/` (managed provider secrets, admin token files) |
| | `cloudflare/` logs and PID files |

Console-managed **runtime providers**, **model_config overrides**, and **built-in provider credentials** live in SQLite + `.nesty/` — they are **not** reverted by bootstrap.

**Ongoing operation**

Keeping **`PY_FILE=bootstrap.py` permanently** is supported and recommended when:

- Panel `git pull` may fail on dirty trees, and
- You want every restart to align tracked code with `origin/main` before Gateway starts.

Optional env (defaults work for most installs):

```env
# NESTY_BOOTSTRAP_GIT_SYNC=true
# NESTY_GIT_BRANCH=main
# NESTY_GIT_REMOTE=origin
```

Set `NESTY_BOOTSTRAP_GIT_SYNC=false` only if you intentionally run a fork or pinned commit without remote sync.

**Troubleshooting**

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Log stops at `git pull` / `Aborting` | Normal when tree is dirty | Ignore if bootstrap banner follows; otherwise fix `PY_FILE` |
| No bootstrap banner | `PY_FILE=run.py` | Set `PY_FILE=bootstrap.py` and restart |
| `ImportError: git_sync` | Old install without repo files | Pull latest or upload `git_sync.py` once |
| `could not reset to origin/main` | Network or missing remote | Check git remote; retry restart |
| Gateway starts but code looks stale | Sync disabled or no `.git` | Enable sync; confirm repo clone |

#### Tunnel and runtime notes

- With `TUNNEL_ENABLED=1` and `CLOUDFLARE_TUNNEL_TOKEN` set, `run.py` starts `cloudflared` automatically before Gateway startup.
- If `cloudflared` binary is missing and `TUNNEL_AUTO_INSTALL_CLOUDFLARED=1`, `run.py` attempts a best-effort install to `CLOUDFLARED_BIN_PATH`.
- If tunnel is disabled or setup fails safely, Gateway still starts normally on local HTTP.
- `CLOUDFLARED_LOG_PATH` and `CLOUDFLARED_PID_PATH` must point to writable directories.
- `.cloudflared/` and `cloudflare/` runtime artifacts should never be committed.
- Gateway still listens locally on HTTP (usually port `8000`).
- Duplicate bootstrap log lines (stdout + stderr) are intentional so panel consoles that capture only one stream still show sync status.

Production reminders:

```env
APP_ENV=production
REQUIRE_API_KEY=true
NESTY_API_KEY_HASH_SECRET=<set-a-strong-secret>
CORS_ALLOW_ORIGINS=https://your-exact-frontend-origin.example.com
TRUSTED_HOSTS=your-tunnel-public-hostname.example.com
INTERNAL_ADMIN_ENABLED=false
```

- Never expose `NESTY_INTERNAL_ADMIN_TOKEN` to browser/mobile clients.
- Verify `/health` and `/ready` through the public tunnel URL after deployment.

---

## 4. Ephemeral Console API Key for Panel Deployments

Some container panel consoles are not interactive shells. In those environments, commands like
`python scripts/create_api_key.py ...` might not run reliably from the panel console.

NestyAI can optionally generate an ephemeral Nesty Console API key at startup:

```env
NESTY_EPHEMERAL_CONSOLE_KEY_ENABLED=true
NESTY_EPHEMERAL_CONSOLE_KEY_NAME=nesty-console-ephemeral
NESTY_EPHEMERAL_CONSOLE_KEY_ENV=prod
NESTY_EPHEMERAL_CONSOLE_KEY_DAILY_LIMIT=10000
NESTY_EPHEMERAL_CONSOLE_KEY_MONTHLY_LIMIT=
NESTY_EPHEMERAL_CONSOLE_KEY_MODELS=nesty-flash-1.0,nesty-combined-1.0,nesty-pro-1.0
NESTY_EPHEMERAL_CONSOLE_KEY_PREFIX=nsk_console
```

Flow:

1. Restart Gateway (`python run.py`, or `bootstrap.py` on panel deployments — see below).
2. Copy the printed `EPHEMERAL NESTY CONSOLE API KEY` value from startup logs.
3. Paste it into Nesty Console Gateway credentials as `NESTY_API_KEY`.
4. On the next Gateway restart, the key rotates and Console credentials must be updated again.

Important notes:

- This startup key is intended for Console-to-Gateway control only, not external users.
- Persistent API keys created via scripts or Console UI remain untouched.
- Never commit or publicly share screenshots of the printed key.
- Internal admin token is separate and should normally stay stable in env:
  - Gateway: `INTERNAL_ADMIN_ENABLED=true` and `NESTY_INTERNAL_ADMIN_TOKEN=...`
  - Console: `NESTY_CONSOLE_ENABLE_INTERNAL_ADMIN=true` and `NESTY_INTERNAL_ADMIN_TOKEN=...`

---

## 5. Production Hardening Settings

When deploying NestyAI to production, configure these security and optimization settings in your `.env`:

```env
# Enforce production mode (disables generic stack trace details in generic errors)
APP_ENV=production

# Security - Enforce API Keys
REQUIRE_API_KEY=true

# Security - Set a strong hash secret (crucial to secure API key matching)
NESTY_API_KEY_HASH_SECRET=your_long_random_secure_secret_string

# Admin API Access - Disable unless active config changes are required
INTERNAL_ADMIN_ENABLED=false

# CORS - NEVER use wildcard '*' in production when REQUIRE_API_KEY=true
CORS_ENABLED=true
CORS_ALLOW_ORIGINS=https://your-exact-app-domain.com

# Hosts - Accept only requests targeted to your host
TRUSTED_HOSTS=your-gateway-host.com
```

---

## 6. Operational Notes

> [!WARNING]
> **Provider Diagnostics & Quotas**: 
> Enabling periodic health checks (like running `benchmark_provider_chains.py` via cron) consumes normal provider token quotas. Adjust check frequencies to be conservative (e.g., once every 15-30 minutes) to prevent hitting provider rate limits.

> [!IMPORTANT]
> **Semantic Recall & Backfill**:
> To use semantic recall, you must enable embeddings (`EMBEDDINGS_ENABLED=true`) and embedding storage (`EMBEDDINGS_STORE_MESSAGE_EMBEDDINGS=true`). For conversations that occurred while embeddings were disabled, run the backfill script:
> ```bash
> python scripts/rebuild_embeddings.py
> ```
