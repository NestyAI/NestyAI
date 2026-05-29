from __future__ import annotations

import os
import sys

import httpx


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _pass(msg: str) -> None:
    print(f"[PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def main() -> int:
    all_required_passed = True

    with httpx.Client(timeout=20.0) as client:
        try:
            health = client.get(f"{BASE_URL}/health")
            if health.status_code == 200 and health.json().get("status") == "ok":
                _pass("GET /health")
            else:
                all_required_passed = False
                _fail(f"GET /health -> {health.status_code} {health.text}")
        except Exception as exc:
            all_required_passed = False
            _fail(f"GET /health exception: {exc}")

        try:
            models = client.get(f"{BASE_URL}/v1/models")
            if models.status_code == 200:
                _pass("GET /v1/models")
            else:
                all_required_passed = False
                _fail(f"GET /v1/models -> {models.status_code} {models.text}")
        except Exception as exc:
            all_required_passed = False
            _fail(f"GET /v1/models exception: {exc}")

        try:
            payload = {
                "model": "nesty-combined-1.0",
                "messages": [{"role": "user", "content": "Hello from smoke test"}],
                "search": "off",
            }
            chat = client.post(f"{BASE_URL}/v1/chat/completions", json=payload)
            if chat.status_code == 200:
                _pass("POST /v1/chat/completions (search=off)")
            else:
                error_code = ""
                try:
                    error_code = chat.json().get("error", {}).get("code", "")
                except Exception:
                    error_code = ""
                if error_code in {"missing_api_key", "all_providers_failed", "provider_unavailable"}:
                    _warn(
                        "POST /v1/chat/completions requires configured provider key/network. "
                        f"Current code: {error_code}"
                    )
                else:
                    all_required_passed = False
                    _fail(f"POST /v1/chat/completions -> {chat.status_code} {chat.text}")
        except Exception as exc:
            all_required_passed = False
            _fail(f"POST /v1/chat/completions exception: {exc}")

    return 0 if all_required_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

