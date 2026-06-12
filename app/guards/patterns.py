from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True)
class GuardPattern:
    name: str
    category: str
    regex: Pattern[str]


GUARD_PATTERNS: list[GuardPattern] = [
    GuardPattern("openai_key", "secret", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    GuardPattern("nesty_admin_token", "secret", re.compile(r"\bnia_[A-Za-z0-9]{8,}\b")),
    GuardPattern("nesty_api_key", "secret", re.compile(r"\bnsk_[A-Za-z0-9_]{8,}\b")),
    GuardPattern("nesty_console_secret", "secret", re.compile(r"\bncc_[A-Za-z0-9]{8,}\b")),
    GuardPattern("groq_key", "secret", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    GuardPattern("openrouter_key", "secret", re.compile(r"\bsk-or-v1-[A-Za-z0-9]{20,}\b")),
    GuardPattern("google_api_key", "secret", re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b")),
    GuardPattern("github_token", "secret", re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b")),
    GuardPattern(
        "jwt",
        "secret",
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    ),
    GuardPattern(
        "bearer_token",
        "secret",
        re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b", flags=re.IGNORECASE),
    ),
    GuardPattern(
        "password_field",
        "secret",
        re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*['\"]?[^'\"\s,;]+"),
    ),
    GuardPattern(
        "api_token_field",
        "secret",
        re.compile(r"(?i)\b(api[_-]?key|token|secret)\s*[:=]\s*['\"]?[^'\"\s,;]+"),
    ),
    GuardPattern(
        "private_key_block",
        "secret",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
            flags=re.MULTILINE,
        ),
    ),
    GuardPattern(
        "database_url",
        "secret",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|mssql|sqlite)://[^\s\"']+",
            flags=re.IGNORECASE,
        ),
    ),
    GuardPattern(
        "email",
        "pii",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    GuardPattern(
        "vietnamese_phone",
        "pii",
        re.compile(r"(?<!\d)(?:\+84|0)(?:3|5|7|8|9)\d{8}(?!\d)"),
    ),
    GuardPattern(
        "ipv4",
        "pii",
        re.compile(
            r"\b(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d?\d)){3}\b"
        ),
    ),
    GuardPattern(
        "windows_path",
        "pii",
        re.compile(r"\b[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*"),
    ),
    GuardPattern(
        "unix_path",
        "pii",
        re.compile(r"(?<![A-Za-z0-9])/((?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+)"),
    ),
]
