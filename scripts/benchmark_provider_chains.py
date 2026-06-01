from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.model_config_loader import list_effective_model_configs
from app.core.provider_diagnostics import (
    diagnose_all_model_aliases,
    diagnose_model_alias,
    diagnose_provider_model,
    extract_configured_provider_targets,
)
from app.deps import get_settings
from app.storage.provider_health import get_latest_provider_health


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


def _target_key(model_alias: str | None, role: str | None, provider: str | None, model: str | None) -> tuple[str, str, str, str]:
    return (
        str(model_alias or "").strip(),
        str(role or "").strip(),
        str(provider or "").strip(),
        str(model or "").strip(),
    )


def _config_revision(config_payload: dict | None) -> str | None:
    if not isinstance(config_payload, dict):
        return None
    encoded = json.dumps(config_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _render_rows(rows: list[dict]) -> str:
    if not rows:
        return "No targets."
    headers = ["model_alias", "role", "provider", "model", "status", "latency_ms", "tps", "error_code"]
    widths = {h: len(h) for h in headers}
    for row in rows:
        widths["model_alias"] = max(widths["model_alias"], len(str(row.get("model_alias") or "")))
        widths["role"] = max(widths["role"], len(str(row.get("role") or "")))
        widths["provider"] = max(widths["provider"], len(str(row.get("provider") or "")))
        widths["model"] = max(widths["model"], len(str(row.get("model") or "")))
        widths["status"] = max(widths["status"], len(str(row.get("status") or "")))
        widths["latency_ms"] = max(widths["latency_ms"], len(str(row.get("latency_ms") if row.get("latency_ms") is not None else "")))
        tps = row.get("tokens_per_second")
        widths["tps"] = max(widths["tps"], len(f"{float(tps):.2f}" if tps is not None else ""))
        widths["error_code"] = max(widths["error_code"], len(str(row.get("error_code") or "")))

    def _line(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[h]) for value, h in zip(values, headers))

    lines = [_line(headers), "-+-".join("-" * widths[h] for h in headers)]
    for row in rows:
        tps = row.get("tokens_per_second")
        lines.append(
            _line(
                [
                    str(row.get("model_alias") or ""),
                    str(row.get("role") or ""),
                    str(row.get("provider") or ""),
                    str(row.get("model") or ""),
                    str(row.get("status") or ""),
                    str(row.get("latency_ms") if row.get("latency_ms") is not None else ""),
                    f"{float(tps):.2f}" if tps is not None else "",
                    str(row.get("error_code") or ""),
                ]
            )
        )
    return "\n".join(lines)


def _summarize_rows(rows: list[dict]) -> dict:
    counts = {"ok": 0, "failed": 0, "skipped": 0, "unavailable": 0, "timeout": 0}
    for row in rows:
        status = str(row.get("status") or "failed").lower()
        if status not in counts:
            status = "failed"
        counts[status] += 1
    return {
        "total": len(rows),
        "ok": counts["ok"],
        "failed": counts["failed"] + counts["timeout"] + counts["unavailable"],
        "status_counts": counts,
    }


def _collect_targets(model_alias: str | None, include_roles: bool) -> list[dict]:
    targets: list[dict] = []
    if model_alias:
        row = next(
            (item for item in list_effective_model_configs() if str(item.get("model_id") or "").strip() == model_alias),
            None,
        )
        effective = row.get("effective_config") if isinstance(row, dict) else None
        if isinstance(effective, dict):
            source = str(row.get("config_source") or "effective").strip().lower() if isinstance(row, dict) else "effective"
            revision = _config_revision(effective)
            targets.extend(
                extract_configured_provider_targets(
                    model_alias=model_alias,
                    model_config=effective,
                    include_roles=include_roles,
                )
            )
            for item in targets:
                item["config_source"] = source
                item["config_revision"] = revision
        return targets

    for row in list_effective_model_configs():
        alias = str(row.get("model_id") or "").strip()
        if not alias:
            continue
        effective = row.get("effective_config")
        if not isinstance(effective, dict):
            continue
        source = str(row.get("config_source") or "effective").strip().lower()
        revision = _config_revision(effective)
        start_index = len(targets)
        targets.extend(
            extract_configured_provider_targets(
                model_alias=alias,
                model_config=effective,
                include_roles=include_roles,
            )
        )
        for item in targets[start_index:]:
            item["config_source"] = source
            item["config_revision"] = revision
    return targets


async def _run(args) -> int:
    settings = get_settings()
    if not bool(getattr(settings, "diagnostics_enabled", True)):
        print("status: diagnostics_disabled")
        return 0

    save_enabled = bool(args.save) and not bool(args.dry_run)
    latest_rows = []
    latest_by_target = {}

    if getattr(args, "only_unhealthy", False):
        try:
            latest_rows = get_latest_provider_health(
                provider=None,
                model_alias=getattr(args, "model_alias", None),
                since_seconds=getattr(args, "since_seconds", None),
            )
            latest_by_target = {
                _target_key(row.get("model_alias"), row.get("role"), row.get("provider"), row.get("model")): row
                for row in latest_rows
            }
        except Exception:
            latest_rows = []
            latest_by_target = {}
    ttl_seconds = max(1, int(getattr(settings, "provider_health_ttl_seconds", 900)))

    rows: list[dict] = []
    summary: dict = {"total": 0, "ok": 0, "failed": 0, "status_counts": {}}

    if args.only_unhealthy:
        targets = _collect_targets(args.model_alias, include_roles=bool(args.include_roles))
        for item in targets:
            key = _target_key(item.get("model_alias"), item.get("role"), item.get("provider"), item.get("model"))
            latest = latest_by_target.get(key)
            if latest is None:
                continue
            latest_status = str(latest.get("status") or "").lower()
            if latest_status == "ok" and not _is_stale(latest.get("checked_at"), ttl_seconds):
                continue
            checked = await diagnose_provider_model(
                provider=str(item.get("provider") or ""),
                model=str(item.get("model") or ""),
                message=args.message,
                model_alias=str(item.get("model_alias") or "") or None,
                role=str(item.get("role") or "") or None,
                order=int(item.get("order") or 0),
                config_source=str(item.get("config_source") or "effective"),
                config_revision=str(item.get("config_revision") or "") or None,
                dry_run=not save_enabled,
            )
            rows.append(checked)
        summary = _summarize_rows(rows)
    else:
        if args.model_alias:
            result = await diagnose_model_alias(
                model_alias=args.model_alias,
                include_roles=bool(args.include_roles),
                message=args.message,
                dry_run=not save_enabled,
            )
        else:
            result = await diagnose_all_model_aliases(
                message=args.message,
                include_roles=bool(args.include_roles),
                dry_run=not save_enabled,
            )
        if "items" in result:
            for item in result.get("items") or []:
                rows.extend(list(item.get("results") or []))
        else:
            rows.extend(list(result.get("results") or []))
        summary = dict(result.get("summary") or summary)

    payload = {
        "ok": True,
        "model_alias": args.model_alias,
        "include_roles": bool(args.include_roles),
        "saved": save_enabled,
        "only_unhealthy": bool(args.only_unhealthy),
        "summary": summary,
        "rows": [
            {
                "model_alias": row.get("model_alias"),
                "role": row.get("role"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "status": row.get("status"),
                "latency_ms": row.get("latency_ms"),
                "tokens_per_second": row.get("tokens_per_second"),
                "error_code": row.get("error_code"),
                "config_source": row.get("config_source"),
                "config_revision": row.get("config_revision"),
            }
            for row in rows
        ],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=True))
        return 0

    print(_render_rows(payload["rows"]))
    summary = payload.get("summary") or {}
    print(f"summary_total: {summary.get('total', 0)}")
    print(f"summary_ok: {summary.get('ok', 0)}")
    print(f"summary_failed: {summary.get('failed', 0)}")
    print("status: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark configured provider chains with small diagnostic prompts.")
    parser.add_argument("--model-alias", type=str, default=None)
    parser.add_argument("--include-roles", action="store_true")
    parser.add_argument("--message", type=str, default="Reply with exactly: OK")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-unhealthy", action="store_true")
    parser.set_defaults(save=True)
    parser.add_argument("--save", dest="save", action="store_true")
    parser.add_argument("--no-save", dest="save", action="store_false")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
