from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import get_settings
from app.storage.api_keys import revoke_api_key


def _resolve_db_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def main() -> int:
    parser = argparse.ArgumentParser(description="Revoke a NestyAI API key.")
    parser.add_argument("--id", required=True, help="API key id, e.g. key_xxx.")
    args = parser.parse_args()

    settings = get_settings()
    db_path = _resolve_db_path(settings.nesty_db_path)
    if not db_path.exists():
        print(f"Database not found at: {db_path}")
        print("Cannot revoke API key because no database exists yet.")
        return 1

    success = revoke_api_key(settings.nesty_db_path, args.id)
    if not success:
        print(f"No active API key found with id: {args.id}")
        return 1

    print(f"API key revoked successfully: {args.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
