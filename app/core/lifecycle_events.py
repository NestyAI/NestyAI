from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


_MAX_LIFECYCLE_EVENTS = 24


class LifecycleEvent(BaseModel):
    type: str
    status: str = "ok"
    error_code: str | None = None
    latency_ms: int | None = None
    count: int | None = None
    provider: str | None = None
    tool: str | None = None


class LifecycleEventCollector:
    def __init__(
        self,
        *,
        request_id: str,
        model_alias: str,
        max_events: int = _MAX_LIFECYCLE_EVENTS,
    ) -> None:
        self.request_id = request_id
        self.model_alias = model_alias
        self.max_events = max(1, min(int(max_events), _MAX_LIFECYCLE_EVENTS))
        self._events: list[LifecycleEvent] = []

    def emit(
        self,
        event_type: str,
        *,
        status: str = "ok",
        error_code: str | None = None,
        latency_ms: int | None = None,
        count: int | None = None,
        provider: str | None = None,
        tool: str | None = None,
    ) -> None:
        if len(self._events) >= self.max_events:
            return
        normalized_type = str(event_type or "").strip()
        if not normalized_type:
            return
        self._events.append(
            LifecycleEvent(
                type=normalized_type,
                status=str(status or "ok").strip() or "ok",
                error_code=_safe_optional_str(error_code),
                latency_ms=_safe_optional_int(latency_ms),
                count=_safe_optional_int(count),
                provider=_safe_optional_str(provider),
                tool=_safe_optional_str(tool),
            )
        )

    def to_metadata(self) -> list[dict[str, Any]]:
        return [event.model_dump(exclude_none=True) for event in self._events]

    def to_models(self) -> list[LifecycleEvent]:
        return list(self._events)


def _safe_optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
