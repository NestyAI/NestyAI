from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deps import get_settings
from app.storage.provider_health import (
    get_latest_provider_health,
    summarize_provider_health,
    list_recent_health_samples,
)
from app.core.provider_reliability import summarize_reliability_for_targets


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


def _render_rows(
    rows: list[dict],
    ttl_seconds: int,
    reliability_by_target: dict | None = None,
    show_reliability: bool = False,
) -> str:
    if not rows:
        return "No provider health check records found. Diagnostics table is empty or has no recent health checks."

    if show_reliability and reliability_by_target:
        headers = ["model_alias", "role", "provider", "model", "latest", "score", "confidence", "samples", "avg_latency"]
    else:
        headers = ["provider", "model_alias", "role", "model", "status", "stale", "latency_ms", "checked_at", "error_code"]

    widths = {h: len(h) for h in headers}

    for row in rows:
        key = (
            str(row.get("provider") or "").strip(),
            str(row.get("model") or "").strip(),
            str(row.get("model_alias") or "").strip(),
            str(row.get("role") or "").strip(),
        )
        rel = reliability_by_target.get(key, {}) if (show_reliability and reliability_by_target) else {}

        for h in headers:
            if h == "stale":
                val = _is_stale(row.get("checked_at"), ttl_seconds)
            elif h == "latest":
                val = row.get("status")
            elif h == "score":
                score = rel.get("reliability_score")
                val = f"{score:.2f}" if score is not None else "-"
            elif h == "confidence":
                val = rel.get("confidence") or "-"
            elif h == "samples":
                val = rel.get("sample_count")
              # Display 'insufficient' for user readability if confidence is insufficient_data
              # but prompt returns standard string
            elif h == "avg_latency":
                val = rel.get("avg_latency_ms")
            else:
                val = row.get(h)

            text = "" if val is None else str(val)
            widths[h] = max(widths[h], len(text))

    def _line(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[h]) for value, h in zip(values, headers))

    lines = [_line(headers), "-+-".join("-" * widths[h] for h in headers)]
    for row in rows:
        key = (
            str(row.get("provider") or "").strip(),
            str(row.get("model") or "").strip(),
            str(row.get("model_alias") or "").strip(),
            str(row.get("role") or "").strip(),
        )
        rel = reliability_by_target.get(key, {}) if (show_reliability and reliability_by_target) else {}

        values = []
        for h in headers:
            if h == "stale":
                val = _is_stale(row.get("checked_at"), ttl_seconds)
            elif h == "latest":
                val = row.get("status")
            elif h == "score":
                score = rel.get("reliability_score")
                val = f"{score:.2f}" if score is not None else "-"
            elif h == "confidence":
                val = rel.get("confidence") or "-"
            elif h == "samples":
                val = rel.get("sample_count")
            elif h == "avg_latency":
                val = rel.get("avg_latency_ms")
            else:
                val = row.get(h)
            values.append("" if val is None else str(val))
        lines.append(_line(values))

    return "\n".join(lines)


def _run(args) -> int:
    settings = get_settings()
    ttl_seconds = max(1, int(getattr(settings, "provider_health_ttl_seconds", 900)))
    limit = max(1, int(getattr(args, "limit", 50) or 50))
    
    rows = get_latest_provider_health(
        provider=getattr(args, "provider", None),
        model_alias=getattr(args, "model_alias", None),
        since_seconds=getattr(args, "since_seconds", None),
    )
    
    if getattr(args, "only_unhealthy", False):
        rows = [
            row
            for row in rows
            if str(row.get("status") or "").lower() != "ok" or _is_stale(row.get("checked_at"), ttl_seconds)
        ]
        
    if len(rows) > limit:
        rows = rows[:limit]
        
    summary = summarize_provider_health(
        provider=getattr(args, "provider", None),
        model_alias=getattr(args, "model_alias", None),
        since_seconds=getattr(args, "since_seconds", None),
    )
    
    scoring_enabled = bool(getattr(settings, "provider_reliability_scoring_enabled", True))
    show_reliability = bool(getattr(args, "show_reliability", True)) and scoring_enabled
    
    reliability_list = []
    reliability_by_target = {}
    
    if show_reliability:
        window_size = int(getattr(args, "window_checks", None) or getattr(settings, "provider_reliability_window_checks", 20))
        
        class ConfigOverride:
            def __init__(self, parent, min_checks):
                self.parent = parent
                self.min_checks = min_checks
            def __getattr__(self, name):
                if name == "provider_reliability_min_checks" and self.min_checks is not None:
                    return self.min_checks
                return getattr(self.parent, name)
                
        run_config = ConfigOverride(settings, getattr(args, "min_checks", None))
        
        recent_samples = list_recent_health_samples(
            provider=getattr(args, "provider", None),
            model_alias=getattr(args, "model_alias", None),
            limit_per_target=window_size,
            since_seconds=getattr(args, "since_seconds", None),
        )
        reliability_list = summarize_reliability_for_targets(recent_samples, run_config)
        reliability_by_target = {
            (
                str(r["provider"]).strip(),
                str(r["model"]).strip(),
                str(r["model_alias"] or "").strip(),
                str(r["role"] or "").strip()
            ): r
            for r in reliability_list
        }
        
    payload = {
        "ok": True,
        "filters": {
            "provider": getattr(args, "provider", None),
            "model_alias": getattr(args, "model_alias", None),
            "limit": limit,
            "since_seconds": getattr(args, "since_seconds", None),
            "only_unhealthy": bool(getattr(args, "only_unhealthy", False)),
        },
        "ttl_seconds": ttl_seconds,
        "summary": summary,
        "latest": rows,
    }
    
    if show_reliability:
        payload["reliability"] = reliability_list
    else:
        payload["reliability_enabled"] = False
        
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=True))
        return 0

    print(_render_rows(rows, ttl_seconds=ttl_seconds, reliability_by_target=reliability_by_target, show_reliability=show_reliability))
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
    parser.add_argument("--show-reliability", dest="show_reliability", action="store_true")
    parser.add_argument("--no-reliability", dest="show_reliability", action="store_false")
    parser.set_defaults(show_reliability=True)
    parser.add_argument("--window-checks", type=int, default=None)
    parser.add_argument("--min-checks", type=int, default=None)
    args = parser.parse_args()
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
