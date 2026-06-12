# NestyAI Gateway Security

NestyAI Gateway v1.5.2 adds deterministic safety policy enforcement for personal/self-host deployments.

## Safety policy modes

| Env var | Values | Default |
|---------|--------|---------|
| `NESTY_SAFETY_POLICY_MODE` | `enforce`, `audit` | `enforce` |

- **enforce** — High-confidence jailbreak, secret exfiltration, and malicious cyber requests are blocked with HTTP 400 `policy_error` before any provider, search, or tool call.
- **audit** — Classifies unsafe input and records metadata only; does not refuse. Intended for local/dev/self-host debugging.

Do not run production-like deployments in `audit` mode unless you understand requests will reach upstream providers unchanged.

## What is blocked (high-confidence)

- Jailbreak / instruction override (`ignore previous instructions`, `developer mode`, reveal hidden prompts)
- Secret exfiltration (`.env` dumps, API keys, admin tokens, console secrets, raw private context)
- Malware creation, credential theft, phishing for theft
- Auth/paywall/DRM/license/rate-limit bypass
- Unauthorized intrusion against real targets

## What remains allowed

- Defensive security education, log analysis, vulnerability explanation
- Password hashing, auth middleware fixes, secure configuration
- Defensive malware analysis and authorized CTF/lab guidance
- Normal coding help (`tokenization`, `key-value pair`, virus scan explanations)

## Guards overview

| Layer | Role |
|-------|------|
| **Safety policy** | Pre-provider classification (`allow` / `refuse` / `sanitize`) |
| **InputGuard** | Secret/PII redaction on messages |
| **ContextGuard** | Prompt-injection phrase removal in untrusted search/tool/memory context (snapshot only — stored memory is not mutated) |
| **OutputGuard** | Secret redaction, internal tool markup removal, unsafe output blocking |

## Streaming limitation (honest)

Streaming responses send raw provider deltas to the client as they arrive. Output guard runs **after** the stream completes. Already-sent tokens are not retroactively redacted in the SSE stream. Metadata and stored assistant content reflect the post-scan sanitized text.

Pre-provider safety refusals still apply to streaming requests (HTTP 400 before SSE begins).

## Policy error codes

| Code | Meaning |
|------|---------|
| `safety_violation` | General policy refusal |
| `secret_exfiltration_blocked` | Request to extract secrets or private context |
| `malicious_cyber_request` | Harmful cyber abuse request |
| `prompt_injection_detected` | Prompt injection in untrusted context (metadata) |
| `unsafe_output_blocked` | Unsafe or sensitive output transformed |

Error envelope shape is unchanged and OpenAI-compatible:

```json
{
  "error": {
    "message": "...",
    "type": "policy_error",
    "code": "secret_exfiltration_blocked",
    "details": { "reason_code": "secret_exfiltration", "request_id": "..." }
  }
}
```

Details never include matched secrets, raw prompts, or provider payloads.

## Runtime provider security

See [RUNTIME_CONFIG.md](RUNTIME_CONFIG.md). Base URLs are SSRF-validated with DNS resolution on create/update/test. Private/local URLs require explicit dev flags.

## Operator warnings

- Anyone with the Internal Admin Token can manage runtime config.
- `NESTY_SAFETY_POLICY_MODE=audit` is not a production safety mode.
- Streaming does not provide live output redaction; treat sensitive deployments accordingly.
