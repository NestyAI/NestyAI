from __future__ import annotations

import os
import platform
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.request import urlretrieve


_CLOUDFLARED_LINUX_AMD64_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
)


@dataclass
class CloudflaredConfig:
    enabled: bool
    token: str
    auto_install: bool
    bin_path: Path
    log_path: Path
    pid_path: Path


@dataclass
class CloudflaredProcess:
    process: subprocess.Popen
    log_handle: TextIO
    pid_path: Path


def is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _warn(message: str) -> None:
    print(f"[WARN] cloudflare_tunnel: {message}", file=sys.stderr)


def get_cloudflared_config_from_env() -> CloudflaredConfig:
    return CloudflaredConfig(
        enabled=is_truthy(os.getenv("TUNNEL_ENABLED")),
        token=str(os.getenv("CLOUDFLARE_TUNNEL_TOKEN", "")).strip(),
        auto_install=is_truthy(os.getenv("TUNNEL_AUTO_INSTALL_CLOUDFLARED", "1")),
        bin_path=Path(os.getenv("CLOUDFLARED_BIN_PATH", "/home/container/.cloudflared/bin/cloudflared")),
        log_path=Path(os.getenv("CLOUDFLARED_LOG_PATH", "./cloudflare/cloudflared.log")),
        pid_path=Path(os.getenv("CLOUDFLARED_PID_PATH", "./cloudflare/cloudflared.pid")),
    )


def _is_supported_auto_install_platform() -> bool:
    system_name = platform.system().strip().lower()
    machine = platform.machine().strip().lower()
    return system_name == "linux" and machine in {"x86_64", "amd64"}


def _download_cloudflared_binary(destination: Path) -> None:
    urlretrieve(_CLOUDFLARED_LINUX_AMD64_URL, destination)


def ensure_cloudflared_binary(config: CloudflaredConfig) -> Path | None:
    binary_path = config.bin_path.expanduser()
    if binary_path.exists():
        return binary_path

    if not config.auto_install:
        _warn(f"cloudflared binary not found at '{binary_path}' and auto-install is disabled.")
        return None

    if not _is_supported_auto_install_platform():
        _warn(
            "cloudflared auto-install is only supported for Linux x86_64/amd64. "
            "Skipping tunnel startup."
        )
        return None

    try:
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        _download_cloudflared_binary(binary_path)
        binary_path.chmod(binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as exc:
        _warn(f"failed to auto-install cloudflared binary: {exc}")
        return None

    if not binary_path.exists():
        _warn("cloudflared auto-install did not produce a binary file.")
        return None
    return binary_path


def start_cloudflared_if_enabled() -> CloudflaredProcess | None:
    config = get_cloudflared_config_from_env()
    if not config.enabled:
        return None

    if not config.token:
        _warn("TUNNEL_ENABLED is true but CLOUDFLARE_TUNNEL_TOKEN is missing. Starting Gateway without tunnel.")
        return None

    binary_path = ensure_cloudflared_binary(config)
    if binary_path is None:
        _warn("cloudflared is unavailable. Starting Gateway without tunnel.")
        return None

    try:
        config.log_path.parent.mkdir(parents=True, exist_ok=True)
        config.pid_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _warn(f"failed to create cloudflared runtime directories: {exc}")
        return None

    try:
        log_handle = config.log_path.open("a", encoding="utf-8")
    except Exception as exc:
        _warn(f"failed to open cloudflared log file '{config.log_path}': {exc}")
        return None

    try:
        process = subprocess.Popen(
            [
                str(binary_path),
                "tunnel",
                "--no-autoupdate",
                "run",
                "--token",
                config.token,
            ],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        config.pid_path.write_text(str(process.pid), encoding="utf-8")
        return CloudflaredProcess(process=process, log_handle=log_handle, pid_path=config.pid_path)
    except Exception as exc:
        _warn(f"failed to start cloudflared process: {exc}")
        try:
            log_handle.close()
        except Exception:
            pass
        return None


def stop_cloudflared(process: CloudflaredProcess | None) -> None:
    if process is None:
        return

    try:
        if process.process.poll() is None:
            process.process.terminate()
            try:
                process.process.wait(timeout=5)
            except Exception:
                process.process.kill()
    except Exception:
        pass

    try:
        process.log_handle.close()
    except Exception:
        pass

    try:
        if process.pid_path.exists():
            process.pid_path.unlink()
    except Exception:
        pass
