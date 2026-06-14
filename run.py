from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Pterodactyl: panel `git pull` may fail on dirty tree; sync tracked files here too.
try:
    from git_sync import sync_git_from_remote

    sync_git_from_remote()
except ImportError:
    pass

import uvicorn
from dotenv import load_dotenv

from app.core.cloudflare_tunnel import start_cloudflared_if_enabled, stop_cloudflared

load_dotenv(PROJECT_ROOT / ".env")


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _start_cloudflared_via_script() -> subprocess.Popen[str] | None:
    if not _is_truthy(os.getenv("TUNNEL_ENABLED")):
        return None

    script_path = Path(__file__).resolve().parent / "scripts" / "start-with-tunnel.sh"
    if not script_path.exists():
        return None

    bash_command = os.getenv("BASH_PATH", "bash")
    try:
        process = subprocess.Popen([bash_command, str(script_path)])
    except FileNotFoundError:
        print("[WARN] tunnel_script: bash is not available; fallback to Python tunnel starter.", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"[WARN] tunnel_script: failed to start script '{script_path}': {exc}", file=sys.stderr)
        return None

    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return process

    print(
        f"[WARN] tunnel_script: script exited early with code {process.returncode}; fallback to Python tunnel starter.",
        file=sys.stderr,
    )
    return None


def _stop_script_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return

    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()
    except Exception:
        pass

    pid_path = Path(os.getenv("CLOUDFLARED_PID_PATH", "./cloudflare/cloudflared.pid"))
    try:
        if pid_path.exists():
            pid_path.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    cloudflared_script_process = _start_cloudflared_via_script()
    cloudflared_process = None if cloudflared_script_process else start_cloudflared_if_enabled()
    try:
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    finally:
        _stop_script_process(cloudflared_script_process)
        stop_cloudflared(cloudflared_process)

