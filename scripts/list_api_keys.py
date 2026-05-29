from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import get_settings
from app.storage.api_keys import list_api_keys


def _resolve_db_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _fmt_models(models: list[str] | None) -> str:
    if not models:
        return "-"
    return json.dumps(models, ensure_ascii=True)


def render_api_key_lines(keys: list[dict]) -> list[str]:
    lines: list[str] = []
    lines.append("id | name | prefix | env | active | daily | monthly | models | created_at | last_used_at")
    for item in keys:
        lines.append(
            " | ".join(
                [
                    str(item["id"]),
                    str(item["name"]),
                    str(item["key_prefix"]),
                    str(item["environment"]),
                    "1" if item["is_active"] else "0",
                    str(item["daily_limit"]) if item["daily_limit"] is not None else "-",
                    str(item["monthly_limit"]) if item["monthly_limit"] is not None else "-",
                    _fmt_models(item["allowed_models"]),
                    str(item["created_at"]),
                    str(item["last_used_at"] or "-"),
                ]
            )
        )
    return lines


def main() -> int:
    settings = get_settings()
    db_path = _resolve_db_path(settings.nesty_db_path)
    if not db_path.exists():
        print(f"Database not found at: {db_path}")
        print("No API keys found.")
        return 0

    keys = list_api_keys(settings.nesty_db_path)

    if not keys:
        print("No API keys found.")
        return 0

    for line in render_api_key_lines(keys):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
