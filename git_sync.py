"""
Git sync helper for Pterodactyl / VPS installs.

Used by bootstrap.py (first recovery) and run.py (ongoing starts after sync).
Does not touch gitignored runtime data (.env, data/, .nesty/).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_PREFIX = "[nesty-git-sync]"


def _is_truthy(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return default


def _log(message: str) -> None:
    line = f"{LOG_PREFIX} {message}"
    print(line, flush=True)
    print(line, file=sys.stderr, flush=True)


def _run_git(args: list[str], *, timeout_seconds: int = 180) -> bool:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        _log("git not found — skip sync")
        return False
    except subprocess.TimeoutExpired:
        _log(f"timeout: git {' '.join(args)}")
        return False
    except Exception as exc:
        _log(f"error running git {' '.join(args)}: {exc}")
        return False

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _log(f"failed: git {' '.join(args)}")
        if detail:
            for line in detail.splitlines()[:10]:
                _log(f"  {line}")
        return False

    _log(f"ok: git {' '.join(args)}")
    return True


def sync_git_from_remote() -> bool:
    """Force tracked files to match origin/<branch>. Returns True when reset succeeded."""
    os.chdir(ROOT)

    if not _is_truthy(os.getenv("NESTY_BOOTSTRAP_GIT_SYNC"), default=True):
        _log("disabled (NESTY_BOOTSTRAP_GIT_SYNC=false)")
        return False
    if not (ROOT / ".git").is_dir():
        _log("no .git directory — skip sync")
        return False

    remote = str(os.getenv("NESTY_GIT_REMOTE", "origin") or "origin").strip() or "origin"
    branch = str(os.getenv("NESTY_GIT_BRANCH", "main") or "main").strip() or "main"
    remote_ref = f"{remote}/{branch}"

    _log(f"syncing tracked files to {remote_ref} (runtime data in .env / data/ / .nesty/ is kept)")

    if not _run_git(["fetch", remote, branch]):
        _log(f"fetch failed — trying reset to existing {remote_ref}")

    if not _run_git(["reset", "--hard", remote_ref]):
        _log(f"could not reset to {remote_ref} — continuing with current files")
        return False

    short = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if short.returncode == 0 and short.stdout.strip():
        _log(f"active commit: {short.stdout.strip()}")

    return True
