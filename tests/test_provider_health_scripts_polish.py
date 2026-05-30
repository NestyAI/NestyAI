from __future__ import annotations

import argparse
import asyncio
import importlib
import json


def test_provider_health_summary_supports_polish_flags(monkeypatch, capsys) -> None:
    module = importlib.import_module("scripts.provider_health_summary")
    monkeypatch.setattr(module, "get_settings", lambda: type("S", (), {"provider_health_ttl_seconds": 900})())
    monkeypatch.setattr(
        module,
        "get_latest_provider_health",
        lambda provider=None, model_alias=None, since_seconds=None: [
            {
                "provider": "openrouter",
                "model_alias": "nesty-combined-1.0",
                "role": "main",
                "model": "m1",
                "status": "ok",
                "latency_ms": 100,
                "checked_at": "2001-01-01T00:00:00+00:00",
                "error_code": None,
            },
            {
                "provider": "groq",
                "model_alias": "nesty-flash-1.0",
                "role": "main",
                "model": "m2",
                "status": "failed",
                "latency_ms": 200,
                "checked_at": "2026-01-01T00:00:00+00:00",
                "error_code": "provider_unavailable",
            },
        ],
    )
    monkeypatch.setattr(
        module,
        "summarize_provider_health",
        lambda provider=None, model_alias=None, since_seconds=None: {
            "total_checks": 2,
            "avg_latency_ms": 150.0,
            "status_counts": {"ok": 1, "failed": 1},
        },
    )
    code = module._run(
        argparse.Namespace(
            limit=10,
            provider=None,
            model_alias=None,
            since_seconds=3600,
            only_unhealthy=True,
            json=True,
        )
    )
    out = capsys.readouterr().out.strip()
    assert code == 0
    payload = json.loads(out)
    assert payload["filters"]["since_seconds"] == 3600
    assert payload["filters"]["only_unhealthy"] is True
    assert len(payload["latest"]) == 2


def test_benchmark_only_unhealthy_tests_subset(monkeypatch, capsys) -> None:
    module = importlib.import_module("scripts.benchmark_provider_chains")
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type("S", (), {"diagnostics_enabled": True, "provider_health_ttl_seconds": 900})(),
    )
    monkeypatch.setattr(
        module,
        "get_latest_provider_health",
        lambda provider=None, model_alias=None, since_seconds=None: [
            {
                "model_alias": "nesty-combined-1.0",
                "role": "main",
                "provider": "openrouter",
                "model": "m1",
                "status": "ok",
                "checked_at": "2099-01-01T00:00:00+00:00",
            },
            {
                "model_alias": "nesty-combined-1.0",
                "role": "main",
                "provider": "groq",
                "model": "m2",
                "status": "failed",
                "checked_at": "2099-01-01T00:00:00+00:00",
            },
        ],
    )
    monkeypatch.setattr(
        module,
        "_collect_targets",
        lambda model_alias, include_roles: [
            {"model_alias": "nesty-combined-1.0", "role": "main", "provider": "openrouter", "model": "m1", "order": 0},
            {"model_alias": "nesty-combined-1.0", "role": "main", "provider": "groq", "model": "m2", "order": 1},
        ],
    )
    called: list[tuple[str, str]] = []

    async def _mock_diag_provider(provider, model, message=None, **kwargs):
        called.append((provider, model))
        return {
            "model_alias": kwargs.get("model_alias"),
            "role": kwargs.get("role"),
            "provider": provider,
            "model": model,
            "status": "ok",
            "latency_ms": 100,
            "tokens_per_second": 10.0,
            "error_code": None,
        }

    monkeypatch.setattr(module, "diagnose_provider_model", _mock_diag_provider)
    args = argparse.Namespace(
        model_alias="nesty-combined-1.0",
        include_roles=False,
        message="Reply with exactly: OK",
        json=True,
        dry_run=True,
        only_unhealthy=True,
        save=True,
    )
    code = asyncio.run(module._run(args))
    out = capsys.readouterr().out.strip()
    assert code == 0
    payload = json.loads(out)
    assert payload["only_unhealthy"] is True
    assert called == [("groq", "m2")]
    assert len(payload["rows"]) == 1
