from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import get_settings
from app.security.api_key import generate_api_key
from app.storage.api_keys import create_api_key_record
from app.storage.db import init_db


def _parse_models(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return models or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a NestyAI API key.")
    parser.add_argument("--name", required=True, help="Human-friendly key name.")
    parser.add_argument("--env", default="dev", choices=["dev", "live"], help="Key environment.")
    parser.add_argument("--daily-limit", type=int, default=None, help="Optional daily request limit.")
    parser.add_argument("--monthly-limit", type=int, default=None, help="Optional monthly request limit.")
    parser.add_argument("--models", default=None, help="Optional comma-separated allowed model aliases.")
    args = parser.parse_args()

    settings = get_settings()
    init_db(settings.nesty_db_path)

    raw_key = generate_api_key(environment=args.env)
    record = create_api_key_record(
        db_path=settings.nesty_db_path,
        name=args.name,
        raw_key=raw_key,
        environment=args.env,
        daily_limit=args.daily_limit,
        monthly_limit=args.monthly_limit,
        allowed_models=_parse_models(args.models),
        hash_secret=settings.nesty_api_key_hash_secret,
    )

    print("API key created successfully.")
    print(f"id: {record['id']}")
    print(f"name: {record['name']}")
    print(f"prefix: {record['key_prefix']}")
    print("raw_api_key (shown once):")
    print(raw_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
