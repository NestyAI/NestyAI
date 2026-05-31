#!/usr/bin/env bash
set -euo pipefail

is_truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

if ! is_truthy "${TUNNEL_ENABLED:-0}"; then
  echo "[INFO] start-with-tunnel: TUNNEL_ENABLED is false; skipping tunnel startup." >&2
  exit 0
fi

if [[ -z "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]]; then
  echo "[WARN] start-with-tunnel: CLOUDFLARE_TUNNEL_TOKEN is missing." >&2
  exit 1
fi

CLOUDFLARED_BIN="${CLOUDFLARED_BIN_PATH:-cloudflared}"
CLOUDFLARED_LOG="${CLOUDFLARED_LOG_PATH:-./cloudflare/cloudflared.log}"
CLOUDFLARED_PID="${CLOUDFLARED_PID_PATH:-./cloudflare/cloudflared.pid}"

mkdir -p "$(dirname "$CLOUDFLARED_LOG")" "$(dirname "$CLOUDFLARED_PID")"

if [[ "$CLOUDFLARED_BIN" == */* ]] || [[ "$CLOUDFLARED_BIN" == *\\* ]]; then
  if [[ ! -x "$CLOUDFLARED_BIN" ]]; then
    if command -v cloudflared >/dev/null 2>&1; then
      echo "[WARN] start-with-tunnel: '$CLOUDFLARED_BIN' missing, fallback to 'cloudflared' in PATH." >&2
      CLOUDFLARED_BIN="cloudflared"
    else
      echo "[WARN] start-with-tunnel: '$CLOUDFLARED_BIN' was not found." >&2
      exit 1
    fi
  fi
fi

if [[ "$CLOUDFLARED_BIN" != */* ]] && [[ "$CLOUDFLARED_BIN" != *\\* ]]; then
  if ! command -v "$CLOUDFLARED_BIN" >/dev/null 2>&1; then
    echo "[WARN] start-with-tunnel: '$CLOUDFLARED_BIN' was not found in PATH." >&2
    exit 1
  fi
fi

echo "[INFO] start-with-tunnel: launching cloudflared..." >&2
echo $$ > "$CLOUDFLARED_PID"

exec "$CLOUDFLARED_BIN" tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" >> "$CLOUDFLARED_LOG" 2>&1
