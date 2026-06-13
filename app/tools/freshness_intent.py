from __future__ import annotations

from dataclasses import dataclass

from app.tools.text_normalize import normalize_message_text


@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    requires_freshness: bool = False
    commodity_or_market_price: bool = False
    news_or_current_events: bool = False
    reason_code: str | None = None


_FRESHNESS_TERMS = [
    "current",
    "today",
    "latest",
    "now",
    "updated",
    "recent",
    "newest",
    "hom nay",
    "hien tai",
    "moi nhat",
    "cap nhat",
    "bay gio",
    "thoi diem nay",
    "gan day",
]

_COMMODITY_PRICE_TERMS = [
    "gia xang",
    "gia dau",
    "gia nhien lieu",
    "gia vang",
    "gia dien",
    "gia ve",
    "gia ca",
    "gasoline price",
    "fuel price",
    "oil price",
    "gold price",
    "electricity price",
    "market price",
    "consumer price",
]

_NEWS_TERMS = [
    "tin moi",
    "tin tuc",
    "news",
    "breaking",
    "headline",
    "the gioi",
    "viet nam",
    "trong nuoc",
    "quoc te",
    "world",
    "vietnam",
]


def detect_freshness_intent(message: str) -> FreshnessDecision:
    normalized = f" {normalize_message_text(message)} "
    commodity = any(term in normalized for term in _COMMODITY_PRICE_TERMS)
    news = any(term in normalized for term in _NEWS_TERMS)
    fresh = any(term in normalized for term in _FRESHNESS_TERMS) or commodity or news
    reason = None
    if commodity:
        reason = "commodity_or_market_price"
    elif news:
        reason = "news_or_current_events"
    elif fresh:
        reason = "freshness_terms"
    return FreshnessDecision(
        requires_freshness=fresh,
        commodity_or_market_price=commodity,
        news_or_current_events=news,
        reason_code=reason,
    )
