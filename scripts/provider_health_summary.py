from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import get_settings
from app.storage.provider_health import get_latest_provider_health, summarize_provider_health


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(checked_at: str | None, ttl_seconds: int) -> bool:
    parsed = _parse_iso(checked_at)
    if parsed is None:
        return True
    age = datetime.now(timezone.utc) - parsed
    return age.total_seconds() > max(1, int(ttl_seconds))


def _render_rows(rows: list[dict], ttl_seconds: int) -> str:
    if not rows:
        return "No provider health checks."
    headers = ["provider", "model_alias", "role", "model", "status", "stale", "latency_ms", "checked_at", "error_code"]
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            value = _is_stale(row.get("checked_at"), ttl_seconds) if h == "stale" else row.get(h)
            text = "" if value is None else str(value)
            widths[h] = max(widths[h], len(text))

    def _line(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[h]) for value, h in zip(values, headers))

    lines = [_line(headers), "-+-".join("-" * widths[h] for h in headers)]
    for row in rows:
        lines.append(
            _line(
                [
                    str(row.get("provider") or ""),
                    str(row.get("model_alias") or ""),
                    str(row.get("role") or ""),
                    str(row.get("model") or ""),
                    str(row.get("status") or ""),
                    str(_is_stale(row.get("checked_at"), ttl_seconds)),
                    str(row.get("latency_ms") if row.get("latency_ms") is not None else ""),
                    str(row.get("checked_at") or ""),
                    str(row.get("error_code") or ""),
                ]
            )
        )
    return "\n".join(lines)


def _run(args) -> int:
    settings = get_settings()
    ttl_seconds = max(1, int(getattr(settings, "provider_health_ttl_seconds", 900)))
    limit = max(1, int(args.limit or 50))
    rows = get_latest_provider_health(
        provider=args.provider,
        model_alias=args.model_alias,
        since_seconds=args.since_seconds,
    )
    if args.only_unhealthy:
        rows = [
            row
            for row in rows
            if str(row.get("status") or "").lower() != "ok" or _is_stale(row.get("checked_at"), ttl_seconds)
        ]
    if len(rows) > limit:
        rows = rows[:limit]
    summary = summarize_provider_health(
        provider=args.provider,
        model_alias=args.model_alias,
        since_seconds=args.since_seconds,
    )
    payload = {
        "ok": True,
        "filters": {
            "provider": args.provider,
            "model_alias": args.model_alias,
            "limit": limit,
            "since_seconds": args.since_seconds,
            "only_unhealthy": bool(args.only_unhealthy),
        },
        "ttl_seconds": ttl_seconds,
        "summary": summary,
        "latest": rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=True))
        return 0

    print(_render_rows(rows, ttl_seconds=ttl_seconds))
    print(f"total_checks: {summary.get('total_checks', 0)}")
    print(f"avg_latency_ms: {summary.get('avg_latency_ms')}")
    print(f"status_counts: {summary.get('status_counts')}")
    print("status: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Print latest provider health diagnostics summary from local SQLite.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--provider", type=str, default=None)
    parser.add_argument("--model-alias", type=str, default=None)
    parser.add_argument("--since-seconds", type=int, default=None)
    parser.add_argument("--only-unhealthy", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
