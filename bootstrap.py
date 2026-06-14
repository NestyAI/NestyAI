"""
Pterodactyl bootstrap entrypoint — recommended panel entry when AUTO UPDATE git pull fails.

Typical locked startup (panel egg):
  if [[ -d .git ]] && [[ "${AUTO_UPDATE}" == "1" ]]; then git pull; fi
  ...
  /usr/local/bin/python /home/container/${PY_FILE} ${APP_ARGS}

Set panel variable PY_FILE = bootstrap.py  (label may say APP PY FILE).

Flow: bootstrap.py -> git_sync.sync_git_from_remote() -> run.py

Optional env:
  NESTY_BOOTSTRAP_GIT_SYNC=false   disable git reset
  NESTY_GIT_BRANCH=main
  NESTY_GIT_REMOTE=origin

See docs/DEPLOYMENT.md (Cloudflare Tunnel — Mode B).
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _banner() -> None:
    lines = [
        "=" * 60,
        "NESTYAI BOOTSTRAP — entrypoint active",
        f"file: {Path(__file__).name}",
        f"root: {ROOT}",
        "If you do NOT see this banner, PY_FILE is still run.py on the panel.",
        "=" * 60,
    ]
    for line in lines:
        print(line, flush=True)
        print(line, file=sys.stderr, flush=True)


def main() -> None:
    _banner()

    from git_sync import sync_git_from_remote

    synced = sync_git_from_remote()
    if synced:
        print("[nesty-bootstrap] git sync complete — starting Gateway", flush=True)
    else:
        print("[nesty-bootstrap] git sync skipped or failed — starting Gateway anyway", flush=True)

    run_path = ROOT / "run.py"
    if not run_path.is_file():
        print(f"[nesty-bootstrap] FATAL: missing {run_path}", file=sys.stderr, flush=True)
        raise SystemExit(1)

    print(f"[nesty-bootstrap] exec {run_path.name}", flush=True)
    runpy.run_path(str(run_path), run_name="__main__")


if __name__ == "__main__":
    main()
