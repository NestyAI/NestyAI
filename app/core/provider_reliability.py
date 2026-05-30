from __future__ import annotations

from typing import Any


def status_to_score(status: str, config: Any) -> float:
    stat = str(status or "").strip().lower()
    if stat == "ok":
        return float(getattr(config, "provider_reliability_ok_score", 1.0))
    elif stat == "failed":
        return float(getattr(config, "provider_reliability_failed_score", 0.0))
    elif stat == "unavailable":
        return float(getattr(config, "provider_reliability_unavailable_score", 0.0))
    elif stat == "timeout":
        return float(getattr(config, "provider_reliability_timeout_score", 0.0))
    elif stat == "skipped":
        return float(getattr(config, "provider_reliability_skipped_score", 0.4))
    else:
        return float(getattr(config, "provider_reliability_failed_score", 0.0))


def compute_latency_score(latency_ms: int | None, samples: list[dict], config: Any) -> float:
    if latency_ms is None or latency_ms <= 0:
        return 0.0
    # Shape-based latency scoring with a simple decay baseline:
    # 300ms or less gets 1.0. Between 300ms and 5000ms is linearly scaled.
    # 5000ms or more gets 0.0.
    if latency_ms <= 300:
        return 1.0
    elif latency_ms >= 5000:
        return 0.0
    else:
        return max(0.0, 1.0 - (latency_ms - 300) / 4700.0)


def compute_stability_score(samples: list[dict]) -> float:
    if not samples:
        return 1.0
    # Map status to binary success (1.0 for ok, 0.0 otherwise)
    scores = [1.0 if s.get("status") == "ok" else 0.0 for s in samples]
    n = len(scores)
    if n <= 1:
        return 1.0
    
    # Calculate standard deviation
    mean = sum(scores) / n
    variance = sum((x - mean) ** 2 for x in scores) / n
    std_dev = variance ** 0.5
    
    # Stability is the inverse of standard deviation
    return max(0.0, 1.0 - std_dev)


def compute_reliability_score(samples: list[dict], config: Any) -> dict:
    sample_count = len(samples)
    min_checks = int(getattr(config, "provider_reliability_min_checks", 3))

    if sample_count == 0:
        return {
            "reliability_score": None,
            "confidence": "insufficient_data",
            "sample_count": 0,
            "ok_count": 0,
            "failed_count": 0,
            "timeout_count": 0,
            "unavailable_count": 0,
            "skipped_count": 0,
            "avg_latency_ms": None,
            "last_status": None,
            "last_checked_at": None,
        }

    # Sort samples by checked_at descending (most recent first)
    sorted_samples = sorted(
        samples,
        key=lambda x: x.get("checked_at") or "",
        reverse=True
    )

    # 1. Recency-weighted status score
    weighted_status_sum = 0.0
    weight_sum = 0.0
    decay = 0.9  # Exponential decay factor for recency
    for idx, s in enumerate(sorted_samples):
        score = status_to_score(s.get("status"), config)
        w = decay ** idx
        weighted_status_sum += score * w
        weight_sum += w

    status_score = (weighted_status_sum / weight_sum) if weight_sum > 0 else 0.0

    # 2. Latency score (only for OK samples)
    ok_latencies = [
        s.get("latency_ms")
        for s in sorted_samples
        if s.get("status") == "ok" and s.get("latency_ms") is not None
    ]
    
    latency_scores = [
        compute_latency_score(lat, sorted_samples, config)
        for lat in ok_latencies
    ]
    
    # If no OK samples, latency score is 0.0
    latency_score = (sum(latency_scores) / len(latency_scores)) if latency_scores else 0.0

    # 3. Stability score
    stability_score = compute_stability_score(sorted_samples)

    # 4. Integrate weighted score
    w_recency = float(getattr(config, "provider_reliability_recency_weight", 0.65))
    w_latency = float(getattr(config, "provider_reliability_latency_weight", 0.20))
    w_stability = float(getattr(config, "provider_reliability_stability_weight", 0.15))

    # Normalize weights just in case they don't sum to 1.0
    w_total = w_recency + w_latency + w_stability
    if w_total > 0:
        w_recency /= w_total
        w_latency /= w_total
        w_stability /= w_total
    else:
        w_recency, w_latency, w_stability = 0.65, 0.20, 0.15

    # Count statuses
    ok_count = sum(1 for s in sorted_samples if s.get("status") == "ok")

    if ok_count == 0:
        reliability_score = 0.0
    else:
        raw_score = (w_recency * status_score) + (w_latency * latency_score) + (w_stability * stability_score)
        reliability_score = max(0.0, min(1.0, round(raw_score, 2)))

    # Determine confidence levels
    if sample_count < min_checks:
        confidence = "insufficient_data"
    elif sample_count <= 5:
        confidence = "low"
    elif sample_count <= 10:
        confidence = "medium"
    else:
        confidence = "high"

    # Count statuses
    failed_count = sum(1 for s in sorted_samples if s.get("status") == "failed")
    timeout_count = sum(1 for s in sorted_samples if s.get("status") == "timeout")
    unavailable_count = sum(1 for s in sorted_samples if s.get("status") == "unavailable")
    skipped_count = sum(1 for s in sorted_samples if s.get("status") == "skipped")

    # Average latency over all OK samples that have it
    avg_latency_ms = None
    if ok_latencies:
        avg_latency_ms = int(round(sum(ok_latencies) / len(ok_latencies)))

    return {
        "reliability_score": reliability_score,
        "confidence": confidence,
        "sample_count": sample_count,
        "ok_count": ok_count,
        "failed_count": failed_count,
        "timeout_count": timeout_count,
        "unavailable_count": unavailable_count,
        "skipped_count": skipped_count,
        "avg_latency_ms": avg_latency_ms,
        "last_status": sorted_samples[0].get("status"),
        "last_checked_at": sorted_samples[0].get("checked_at"),
    }


def summarize_reliability_for_targets(targets_or_rows: list[dict], config: Any) -> list[dict]:
    # Group rows by target keys: (provider, model, model_alias, role)
    grouped: dict[tuple[str, str, str, str], list[dict]] = {}
    for row in targets_or_rows:
        provider = str(row.get("provider") or "").strip()
        model = str(row.get("model") or "").strip()
        model_alias = str(row.get("model_alias") or "").strip()
        role = str(row.get("role") or "").strip()
        key = (provider, model, model_alias, role)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(row)

    results = []
    for key, samples in grouped.items():
        provider, model, model_alias, role = key
        # Compute scoring
        metrics = compute_reliability_score(samples, config)
        results.append({
            "provider": provider,
            "model": model,
            "model_alias": model_alias or None,
            "role": role or None,
            "reliability_score": metrics["reliability_score"],
            "confidence": metrics["confidence"],
            "sample_count": metrics["sample_count"],
            "ok_count": metrics["ok_count"],
            "failed_count": metrics["failed_count"],
            "timeout_count": metrics["timeout_count"],
            "unavailable_count": metrics["unavailable_count"],
            "skipped_count": metrics["skipped_count"],
            "avg_latency_ms": metrics["avg_latency_ms"],
            "last_status": metrics["last_status"],
            "last_checked_at": metrics["last_checked_at"],
        })

    # Sort results by provider, model, model_alias, role for deterministic output
    return sorted(
        results,
        key=lambda x: (
            x.get("provider") or "",
            x.get("model") or "",
            x.get("model_alias") or "",
            x.get("role") or ""
        )
    )
