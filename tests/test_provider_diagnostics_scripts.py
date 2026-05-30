from __future__ import annotations

import argparse
import asyncio
import importlib
import json


def test_benchmark_provider_chains_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.benchmark_provider_chains")
    assert callable(module.main)


def test_provider_health_summary_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.provider_health_summary")
    assert callable(module.main)


def test_benchmark_provider_chains_json_output(monkeypatch, capsys) -> None:
    module = importlib.import_module("scripts.benchmark_provider_chains")
    monkeypatch.setattr(module, "get_settings", lambda: type("S", (), {"diagnostics_enabled": True})())

    async def _mock_diag_alias(model_alias, include_roles=True, message=None, dry_run=False):
        return {
            "summary": {"total": 1, "ok": 1, "failed": 0},
            "results": [
                {
                    "model_alias": model_alias,
                    "role": "main",
                    "provider": "openrouter",
                    "model": "deepseek/deepseek-v4-flash:free",
                    "status": "ok",
                    "latency_ms": 100,
                    "tokens_per_second": 10.0,
                    "error_code": None,
                }
            ],
        }

    monkeypatch.setattr(module, "diagnose_model_alias", _mock_diag_alias)
    args = argparse.Namespace(
        model_alias="nesty-combined-1.0",
        include_roles=False,
        message="Reply with exactly: OK",
        json=True,
        dry_run=True,
        only_unhealthy=False,
        save=True,
    )
    code = asyncio.run(module._run(args))
    out = capsys.readouterr().out.strip()
    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["rows"][0]["status"] == "ok"


def test_provider_health_summary_json_output(monkeypatch, capsys) -> None:
    module = importlib.import_module("scripts.provider_health_summary")
    monkeypatch.setattr(
        module,
        "get_latest_provider_health",
        lambda provider=None, model_alias=None, since_seconds=None: [
            {
                "provider": "openrouter",
                "model_alias": "nesty-combined-1.0",
                "role": "main",
                "model": "deepseek/deepseek-v4-flash:free",
                "status": "ok",
                "latency_ms": 120,
                "checked_at": "2026-01-01T00:00:00+00:00",
                "error_code": None,
            }
        ],
    )
    monkeypatch.setattr(
        module,
        "summarize_provider_health",
        lambda provider=None, model_alias=None, since_seconds=None: {
            "total_checks": 1,
            "avg_latency_ms": 120.0,
            "status_counts": {"ok": 1},
        },
    )
    monkeypatch.setattr(module, "get_settings", lambda: type("S", (), {"provider_health_ttl_seconds": 900})())
    code = module._run(
        argparse.Namespace(
            limit=10,
            provider=None,
            model_alias=None,
            since_seconds=None,
            only_unhealthy=False,
            json=True,
        )
    )
    out = capsys.readouterr().out.strip()
    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["latest"][0]["provider"] == "openrouter"
