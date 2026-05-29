from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import get_settings
from app.storage.usage import get_usage_summary


def _resolve_db_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _group_counts(rows: list[dict], key_name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row.get(key_name, "") or "-")
        result[key] = result.get(key, 0) + int(row.get("request_count", 0))
    return result


def _print_group(title: str, data: dict[str, int]) -> None:
    print(title)
    if not data:
        print("  -")
        return
    for key, value in sorted(data.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Show NestyAI usage summary.")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days.")
    args = parser.parse_args()

    settings = get_settings()
    db_path = _resolve_db_path(settings.nesty_db_path)
    if not db_path.exists():
        print(f"Database not found at: {db_path}")
        print("No usage logs found for the selected period.")
        return 0

    summary = get_usage_summary(settings.nesty_db_path, days=args.days)

    if not summary:
        print("No usage logs found for the selected period.")
        return 0

    total_requests = sum(int(row["request_count"]) for row in summary)
    by_status = _group_counts(summary, "status")
    by_model = _group_counts(summary, "model")
    by_provider = _group_counts(summary, "provider")
    success_count = by_status.get("success", 0)
    error_count = total_requests - success_count

    print(f"Usage Summary (last {max(1, int(args.days))} day(s))")
    print(f"Total requests: {total_requests}")
    print(f"Success count: {success_count}")
    print(f"Error count: {error_count}")
    print("")
    _print_group("Requests by status:", by_status)
    _print_group("Requests by model:", by_model)
    _print_group("Requests by provider:", by_provider)
    print("")
    print("api_key_id | model | provider | status | request_count")
    for row in summary:
        print(
            " | ".join(
                [
                    str(row["api_key_id"]),
                    str(row["model"] or "-"),
                    str(row["provider"] or "-"),
                    str(row["status"]),
                    str(row["request_count"]),
                ]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
