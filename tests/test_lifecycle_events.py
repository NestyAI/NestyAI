from __future__ import annotations

from app.core.lifecycle_events import LifecycleEventCollector


def test_lifecycle_collector_caps_events() -> None:
    collector = LifecycleEventCollector(request_id="req_1", model_alias="nesty-combined-1.0", max_events=3)
    for index in range(5):
        collector.emit("chat.request_started", count=index)
    metadata = collector.to_metadata()
    assert len(metadata) == 3
    assert metadata[0]["type"] == "chat.request_started"


def test_lifecycle_metadata_excludes_none_and_secrets_shape() -> None:
    collector = LifecycleEventCollector(request_id="req_2", model_alias="nesty-flash-1.0")
    collector.emit(
        "search.completed",
        count=2,
        latency_ms=120,
        provider="ddgs",
    )
    payload = collector.to_metadata()[0]
    assert payload["type"] == "search.completed"
    assert payload["count"] == 2
    assert "prompt" not in payload
    assert "message" not in payload
    assert "stack" not in payload
