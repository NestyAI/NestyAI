from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

SafetyAction = Literal["allow", "refuse", "sanitize", "metadata_only"]


@dataclass(slots=True)
class SafetyDecision:
    action: SafetyAction
    reason_code: str
    user_safe_message: str | None = None
    categories: list[str] = field(default_factory=list)


_REFUSAL_MESSAGES: dict[str, str] = {
    "jailbreak_attempt": (
        "I can't override system or developer instructions or disable safety controls. "
        "Ask a direct question about your task and I'll help within Gateway policy."
    ),
    "internal_prompt_request": (
        "I can't reveal internal system prompts, hidden instructions, or private Gateway configuration. "
        "I can explain what the public API supports or help with your integration."
    ),
    "secret_exfiltration": (
        "I can't help extract or reveal secrets, API keys, tokens, environment values, or private context. "
        "For security best practices, I can explain how to store and rotate credentials safely."
    ),
    "malicious_cyber": (
        "I can't help with that request because it appears aimed at harmful or unauthorized activity. "
        "I can help with defensive hardening, detection, or secure configuration instead."
    ),
    "malware_creation": (
        "I can't help create or modify malware, ransomware, keyloggers, or similar harmful software. "
        "I can help analyze suspicious code defensively or improve detection and incident response."
    ),
    "credential_theft": (
        "I can't help steal credentials or build phishing or social-engineering attacks. "
        "I can help secure authentication, monitor abuse, or review auth middleware safely."
    ),
    "bypass_request": (
        "I can't help bypass authentication, licensing, paywalls, DRM, or rate limits. "
        "I can help implement legitimate access controls or fix auth bugs in your own code."
    ),
    "unauthorized_intrusion": (
        "I can't help with unauthorized scanning, intrusion, or exploitation against systems you don't own. "
        "I can help with defensive testing in authorized lab/CTF environments or hardening guidance."
    ),
    "prompt_injection": (
        "I can't follow instructions embedded in untrusted retrieved content. "
        "Ask your question directly and I'll use retrieved data only as reference."
    ),
    "unsafe_tool_instruction": (
        "I can't execute unsafe instructions found in tool or search output. "
        "Rephrase your request as a direct question."
    ),
    "unsafe_output_blocked": (
        "I can't provide that response because it may include unsafe or sensitive content. "
        "Ask for defensive guidance or a high-level explanation instead."
    ),
    "normal": "",
    "allowed_defensive_security": "",
}


_REASON_TO_API_CODE: dict[str, str] = {
    "jailbreak_attempt": "safety_violation",
    "internal_prompt_request": "safety_violation",
    "secret_exfiltration": "secret_exfiltration_blocked",
    "malicious_cyber": "malicious_cyber_request",
    "malware_creation": "malicious_cyber_request",
    "credential_theft": "malicious_cyber_request",
    "bypass_request": "malicious_cyber_request",
    "unauthorized_intrusion": "malicious_cyber_request",
    "prompt_injection": "prompt_injection_detected",
    "unsafe_tool_instruction": "safety_violation",
    "unsafe_output_blocked": "unsafe_output_blocked",
}


def _ascii_fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    folded = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.lower().split())


def _compile_patterns(raw: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for item in raw:
        name, _, expr = item.partition(":")
        name = name.strip() or "pattern"
        expr = expr.strip() if expr.strip() else item.strip()
        if not expr:
            continue
        compiled.append((name, re.compile(expr, flags=re.IGNORECASE)))
    return compiled


_DEFAULT_DEFENSIVE_ALLOW = [
    "defensive_allow:how (?:to|do i) (?:secure|protect|hash|salt|encrypt|validate|sanitize|prevent)",
    "defensive_allow:password hash",
    "defensive_allow:hash passwords",
    "defensive_allow:fix (?:this|my|the) auth",
    "defensive_allow:auth middleware",
    "defensive_allow:log analysis",
    "defensive_allow:analyze (?:this|a|the) suspicious",
    "defensive_allow:malware analysis",
    "defensive_allow:explain (?:sql injection|xss|csrf|ssrf)",
    "defensive_allow:vulnerability (?:explain|explanation|overview)",
    "defensive_allow:ctf|capture the flag|authorized lab|lab environment|my own system",
    "defensive_allow:incident response|hardening|detection rule",
    "defensive_allow:tokenization|key-value pair|virus scan",
    "defensive_allow:phòng chống|bảo mật|giải thích lỗ hổng|phân tích mã độc",
]

_DEFAULT_DENY = [
    "jailbreak:ignore (?:all )?(?:previous|prior|above|system|developer) instructions",
    "jailbreak:disregard (?:the )?(?:system|developer) (?:prompt|instructions|message)",
    "jailbreak:reveal.{0,60}(?:system|developer|hidden|internal) (?:prompt|instructions|policy)",
    "jailbreak:developer mode|dan mode|jailbreak|bypass guardrails|disable safety",
    "jailbreak:print (?:the )?hidden (?:prompt|instructions|policy)",
    "jailbreak:bỏ qua hướng dẫn|lộ prompt nội bộ|bỏ qua hệ thống",
    "exfiltration:dump (?:the )?env|show (?:me )?(?:the )?\\.env|read (?:the )?\\.env",
    "exfiltration:reveal (?:the )?(?:api key|admin token|console secret|provider secret|internal prompt)",
    "exfiltration:print (?:all )?(?:secrets|tokens|hidden context|raw tool context)",
    "exfiltration:lấy api key|đọc file \\.env|lộ token|lộ secret",
    "malware:(?:create|write|build|generate|modify).{0,40}(?:malware|virus|ransomware|keylogger|trojan|rootkit|worm)",
    "malware:tạo virus|tao virus|tạo mã độc|tao ma doc|viết malware",
    "credential_theft:steal (?:passwords|credentials|api keys|tokens|session cookies)",
    "credential_theft:phishing (?:kit|page|email).{0,30}(?:steal|capture|harvest)",
    "credential_theft:hack tài khoản|hack tai khoan|đánh cắp mật khẩu|danh cap mat khau",
    "bypass:bypass (?:login|authentication|paywall|drm|license|rate limit|2fa|mfa)",
    "bypass:bypass đăng nhập|bypass dang nhap|bypass ang nhap|vượt paywall",
    "intrusion:(?:scan|hack|exploit).{0,40}(?:target|website|server|database).{0,40}(?:without permission|unauthorized)",
    "intrusion:unauthorized (?:scan|access|intrusion|penetration)",
]

_DEFAULT_OUTPUT_DENY = [
    "output_malware:here (?:is|are) (?:the )?(?:malware|ransomware|keylogger|trojan)",
    "output_exfil:-----BEGIN (?:RSA )?PRIVATE KEY-----",
    "output_exfil:NESTY_INTERNAL_ADMIN_TOKEN|X-Nesty-Console-Secret",
]


class SafetyPolicy:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        policy_rules = (rules or {}).get("safety_policy", {})
        self.mode = str(policy_rules.get("mode_default", "enforce")).strip().lower()
        self.defensive_allow = _compile_patterns(
            list(policy_rules.get("defensive_allow_patterns") or _DEFAULT_DEFENSIVE_ALLOW)
        )
        self.deny_patterns = _compile_patterns(list(policy_rules.get("deny_patterns") or _DEFAULT_DENY))
        self.output_deny_patterns = _compile_patterns(
            list(policy_rules.get("output_deny_patterns") or _DEFAULT_OUTPUT_DENY)
        )

    def classify_user_input(self, text: str, *, mode: str | None = None) -> SafetyDecision:
        effective_mode = str(mode or self.mode or "enforce").strip().lower()
        if effective_mode not in {"enforce", "audit"}:
            effective_mode = "enforce"

        normalized = _ascii_fold(text)
        if not normalized:
            return SafetyDecision(action="allow", reason_code="normal")

        defensive_hit = any(pattern.search(normalized) for _, pattern in self.defensive_allow)

        for name, pattern in self.deny_patterns:
            if not pattern.search(normalized):
                continue
            category = name.split("_", 1)[0] if "_" in name else name
            reason = {
                "jailbreak": "jailbreak_attempt",
                "exfiltration": "secret_exfiltration",
                "malware": "malware_creation",
                "credential": "credential_theft",
                "bypass": "bypass_request",
                "intrusion": "unauthorized_intrusion",
            }.get(category, "malicious_cyber")

            if reason == "internal_prompt_request":
                pass
            if "internal" in name or "prompt" in name:
                reason = "internal_prompt_request"

            if defensive_hit and reason in {"malicious_cyber", "malware_creation", "credential_theft", "bypass_request", "unauthorized_intrusion"}:
                continue

            if effective_mode == "audit":
                return SafetyDecision(
                    action="metadata_only",
                    reason_code=reason,
                    categories=[name],
                )

            return SafetyDecision(
                action="refuse",
                reason_code=reason,
                user_safe_message=user_refusal_message(reason),
                categories=[name],
            )

        if defensive_hit:
            return SafetyDecision(action="allow", reason_code="allowed_defensive_security")

        return SafetyDecision(action="allow", reason_code="normal")

    def classify_output(self, text: str) -> SafetyDecision:
        normalized = _ascii_fold(text)
        if not normalized:
            return SafetyDecision(action="allow", reason_code="normal")

        for name, pattern in self.output_deny_patterns:
            if pattern.search(normalized):
                return SafetyDecision(
                    action="sanitize",
                    reason_code="unsafe_output_blocked",
                    user_safe_message=user_refusal_message("unsafe_output_blocked"),
                    categories=[name],
                )

        if re.search(r"\bnia_[A-Za-z0-9]{8,}\b", text) or re.search(r"\bncc_[A-Za-z0-9]{8,}\b", text):
            return SafetyDecision(
                action="sanitize",
                reason_code="unsafe_output_blocked",
                user_safe_message=user_refusal_message("unsafe_output_blocked"),
                categories=["nesty_token_leak"],
            )

        return SafetyDecision(action="allow", reason_code="normal")


def user_refusal_message(reason_code: str) -> str:
    return _REFUSAL_MESSAGES.get(reason_code, _REFUSAL_MESSAGES["malicious_cyber"])


def reason_to_api_code(reason_code: str) -> str:
    return _REASON_TO_API_CODE.get(reason_code, "safety_violation")


def build_policy_error_details(decision: SafetyDecision, *, request_id: str | None = None) -> dict[str, Any]:
    details: dict[str, Any] = {"reason_code": decision.reason_code}
    if request_id:
        details["request_id"] = request_id
    if decision.categories:
        details["categories_count"] = len(decision.categories)
    return details
