from __future__ import annotations

import uvicorn

from app.core.cloudflare_tunnel import start_cloudflared_if_enabled, stop_cloudflared


if __name__ == "__main__":
    cloudflared_process = start_cloudflared_if_enabled()
    try:
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    finally:
        stop_cloudflared(cloudflared_process)

