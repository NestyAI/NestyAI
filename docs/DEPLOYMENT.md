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
   Edit `.env` and set at least one provider API key (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, etc.).
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

Notes:

- Panel startup command should be:
  ```bash
  python run.py
  ```
- With `TUNNEL_ENABLED=1` and `CLOUDFLARE_TUNNEL_TOKEN` set, `python run.py` starts `cloudflared` automatically before Gateway startup.
- If `cloudflared` binary is missing and `TUNNEL_AUTO_INSTALL_CLOUDFLARED=1`, `run.py` attempts a best-effort install to `CLOUDFLARED_BIN_PATH`.
- If tunnel is disabled or setup fails safely, Gateway still starts normally on local HTTP.
- `CLOUDFLARED_LOG_PATH` and `CLOUDFLARED_PID_PATH` must point to writable directories.
- `.cloudflared/` and `cloudflare/` runtime artifacts should never be committed.
- Gateway still listens locally on HTTP (usually port `8000`).

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

## 4. Production Hardening Settings

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

## 5. Operational Notes

> [!WARNING]
> **Provider Diagnostics & Quotas**: 
> Enabling periodic health checks (like running `benchmark_provider_chains.py` via cron) consumes normal provider token quotas. Adjust check frequencies to be conservative (e.g., once every 15-30 minutes) to prevent hitting provider rate limits.

> [!IMPORTANT]
> **Semantic Recall & Backfill**:
> To use semantic recall, you must enable embeddings (`EMBEDDINGS_ENABLED=true`) and embedding storage (`EMBEDDINGS_STORE_MESSAGE_EMBEDDINGS=true`). For conversations that occurred while embeddings were disabled, run the backfill script:
> ```bash
> python scripts/rebuild_embeddings.py
> ```
