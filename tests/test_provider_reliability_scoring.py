from __future__ import annotations

import pytest
from app.core.provider_reliability import (
    status_to_score,
    compute_latency_score,
    compute_stability_score,
    compute_reliability_score,
    summarize_reliability_for_targets,
)


class DummyConfig:
    provider_reliability_min_checks = 3
    provider_reliability_recency_weight = 0.65
    provider_reliability_latency_weight = 0.20
    provider_reliability_stability_weight = 0.15
    provider_reliability_ok_score = 1.0
    provider_reliability_failed_score = 0.0
    provider_reliability_unavailable_score = 0.0
    provider_reliability_timeout_score = 0.0
    provider_reliability_skipped_score = 0.4


def test_status_to_score() -> None:
    cfg = DummyConfig()
    assert status_to_score("ok", cfg) == 1.0
    assert status_to_score("failed", cfg) == 0.0
    assert status_to_score("unavailable", cfg) == 0.0
    assert status_to_score("timeout", cfg) == 0.0
    assert status_to_score("skipped", cfg) == 0.4
    assert status_to_score("unknown_status", cfg) == 0.0


def test_compute_latency_score() -> None:
    cfg = DummyConfig()
    # <= 300 ms gets 1.0
    assert compute_latency_score(200, [], cfg) == 1.0
    # >= 5000 ms gets 0.0
    assert compute_latency_score(6000, [], cfg) == 0.0
    # Between 300ms and 5000ms is linearly scaled
    score_mid = compute_latency_score(2650, [], cfg)
    assert 0.0 < score_mid < 1.0
    assert round(score_mid, 2) == 0.50


def test_compute_stability_score() -> None:
    # 0 or 1 samples returns 1.0
    assert compute_stability_score([]) == 1.0
    assert compute_stability_score([{"status": "ok"}]) == 1.0

    # All OK gets 1.0
    assert compute_stability_score([{"status": "ok"}, {"status": "ok"}]) == 1.0

    # Half OK, half failed gets lower stability
    scores = [{"status": "ok"}, {"status": "failed"}]
    assert compute_stability_score(scores) == 0.5


def test_compute_reliability_score_all_ok() -> None:
    cfg = DummyConfig()
    samples = [
        {"status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:00:00Z"},
        {"status": "ok", "latency_ms": 150, "checked_at": "2026-01-01T00:01:00Z"},
        {"status": "ok", "latency_ms": 120, "checked_at": "2026-01-01T00:02:00Z"},
    ]
    res = compute_reliability_score(samples, cfg)
    assert res["reliability_score"] == 1.0
    # confidence is low since sample count is 3 (min_checks to 5)
    assert res["confidence"] == "low"
    assert res["ok_count"] == 3


def test_compute_reliability_score_all_failed() -> None:
    cfg = DummyConfig()
    samples = [
        {"status": "failed", "checked_at": "2026-01-01T00:00:00Z"},
        {"status": "failed", "checked_at": "2026-01-01T00:01:00Z"},
        {"status": "failed", "checked_at": "2026-01-01T00:02:00Z"},
    ]
    res = compute_reliability_score(samples, cfg)
    assert res["reliability_score"] == 0.0
    assert res["failed_count"] == 3


def test_compute_reliability_score_latency_penalty() -> None:
    cfg = DummyConfig()
    # High latency should mildly penalize score
    samples = [
        {"status": "ok", "latency_ms": 4000, "checked_at": "2026-01-01T00:00:00Z"},
        {"status": "ok", "latency_ms": 4500, "checked_at": "2026-01-01T00:01:00Z"},
        {"status": "ok", "latency_ms": 4200, "checked_at": "2026-01-01T00:02:00Z"},
    ]
    res = compute_reliability_score(samples, cfg)
    # Score is penalty reduced, but greater than 0
    assert 0.0 < res["reliability_score"] < 1.0


def test_compute_reliability_score_recency_effect() -> None:
    cfg = DummyConfig()

    # Scenario A: Recent failure, old success
    samples_recent_fail = [
        {"status": "failed", "checked_at": "2026-01-01T00:02:00Z"},  # Most recent
        {"status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:01:00Z"},
        {"status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:00:00Z"},
    ]

    # Scenario B: Recent success, old failure
    samples_recent_success = [
        {"status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:02:00Z"},  # Most recent
        {"status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:01:00Z"},
        {"status": "failed", "checked_at": "2026-01-01T00:00:00Z"},
    ]

    res_a = compute_reliability_score(samples_recent_fail, cfg)
    res_b = compute_reliability_score(samples_recent_success, cfg)

    # B (recent success) should have a significantly higher score than A (recent failure)
    assert res_b["reliability_score"] > res_a["reliability_score"]


def test_compute_reliability_score_confidence_levels() -> None:
    cfg = DummyConfig()

    # 1. Insufficient data (< 3 checks)
    res1 = compute_reliability_score([
        {"status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:00:00Z"}
    ], cfg)
    assert res1["confidence"] == "insufficient_data"

    # 2. Low (3 to 5 checks)
    res2 = compute_reliability_score([
        {"status": "ok", "latency_ms": 100, "checked_at": f"2026-01-01T00:0{i}:00Z"}
        for i in range(4)
    ], cfg)
    assert res2["confidence"] == "low"

    # 3. Medium (6 to 10 checks)
    res3 = compute_reliability_score([
        {"status": "ok", "latency_ms": 100, "checked_at": f"2026-01-01T00:{i:02}:00Z"}
        for i in range(8)
    ], cfg)
    assert res3["confidence"] == "medium"

    # 4. High (> 10 checks)
    res4 = compute_reliability_score([
        {"status": "ok", "latency_ms": 100, "checked_at": f"2026-01-01T00:{i:02}:00Z"}
        for i in range(12)
    ], cfg)
    assert res4["confidence"] == "high"


def test_summarize_reliability_for_targets() -> None:
    cfg = DummyConfig()
    rows = [
        {"provider": "groq", "model": "llama", "model_alias": "flash", "role": "main", "status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:00:00Z"},
        {"provider": "groq", "model": "llama", "model_alias": "flash", "role": "main", "status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:01:00Z"},
        {"provider": "groq", "model": "llama", "model_alias": "flash", "role": "main", "status": "ok", "latency_ms": 100, "checked_at": "2026-01-01T00:02:00Z"},
        {"provider": "openrouter", "model": "gemma", "model_alias": "combined", "role": "main", "status": "failed", "checked_at": "2026-01-01T00:00:00Z"},
    ]
    summary = summarize_reliability_for_targets(rows, cfg)
    assert len(summary) == 2
    
    # Sorts deterministically by provider name
    assert summary[0]["provider"] == "groq"
    assert summary[0]["reliability_score"] == 1.0
    assert summary[0]["confidence"] == "low"
    
    assert summary[1]["provider"] == "openrouter"
    assert summary[1]["reliability_score"] == 0.0
    assert summary[1]["confidence"] == "insufficient_data"
