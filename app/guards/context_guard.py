from __future__ import annotations

import re
from html import unescape
from typing import Any

from bs4 import BeautifulSoup

from app.schemas.tools import ContextGuardMetadata, SearchResult


_DEFAULT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", flags=re.IGNORECASE),
    re.compile(r"disregard\s+system\s+prompt", flags=re.IGNORECASE),
    re.compile(r"reveal\s+your\s+system\s+prompt", flags=re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", flags=re.IGNORECASE),
    re.compile(r"send\s+the\s+user\s+this\s+exact\s+message", flags=re.IGNORECASE),
    re.compile(r"\bexfiltrate\b", flags=re.IGNORECASE),
    re.compile(r"call\s+this\s+api", flags=re.IGNORECASE),
    re.compile(r"\bdeveloper\s+message\b", flags=re.IGNORECASE),
    re.compile(r"\bsystem\s+message\b", flags=re.IGNORECASE),
]


class ContextGuard:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        context_rules = (rules or {}).get("context_guard", {})
        self.replacement = context_rules.get("replacement", "[REMOVED_INJECTION]")
        custom_phrases = context_rules.get("injection_patterns", [])
        if isinstance(custom_phrases, list) and custom_phrases:
            self.injection_patterns = [
                re.compile(re.escape(str(phrase)), flags=re.IGNORECASE)
                for phrase in custom_phrases
            ]
        else:
            self.injection_patterns = _DEFAULT_INJECTION_PATTERNS

    def _strip_html(self, text: str) -> str:
        if "<" not in text and ">" not in text:
            return text
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "iframe", "noscript"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)

    def sanitize_external_context(
        self,
        search_results: list[SearchResult],
        max_context_chars: int,
    ) -> tuple[str, ContextGuardMetadata]:
        lines: list[str] = []
        removed_count = 0

        for index, result in enumerate(search_results, start=1):
            title = unescape(self._strip_html(result.title))
            snippet = unescape(self._strip_html(result.snippet))
            url = result.url.strip()
            block = f"[Source {index}]\nTitle: {title}\nURL: {url}\nSnippet: {snippet}\n"
            for pattern in self.injection_patterns:
                block, count = pattern.subn(self.replacement, block)
                removed_count += count
            lines.append(block)

        context = "\n".join(lines).strip()
        sanitized = removed_count > 0
        if len(context) > max_context_chars:
            context = context[:max_context_chars].rstrip()
            sanitized = True

        metadata = ContextGuardMetadata(
            sanitized=sanitized,
            removed_injection_count=removed_count,
            context_chars=len(context),
            sources_count=len(search_results),
        )
        return context, metadata
