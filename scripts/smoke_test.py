from __future__ import annotations

import os
import sys

import httpx


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SMOKE_TEST_STREAM = os.getenv("SMOKE_TEST_STREAM", "false").strip().lower() in {"1", "true", "yes", "on"}
NESTY_API_KEY = os.getenv("NESTY_API_KEY", "").strip()


def _pass(msg: str) -> None:
    print(f"[PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def main() -> int:
    all_required_passed = True

    with httpx.Client(timeout=20.0) as client:
        auth_headers = {}
        if NESTY_API_KEY:
            auth_headers["Authorization"] = f"Bearer {NESTY_API_KEY}"

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
            chat = client.post(f"{BASE_URL}/v1/chat/completions", json=payload, headers=auth_headers)
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

        if SMOKE_TEST_STREAM:
            try:
                payload = {
                    "model": "nesty-combined-1.0",
                    "messages": [{"role": "user", "content": "Hello streaming smoke test"}],
                    "stream": True,
                    "search": "off",
                    "tools": "off",
                }
                with client.stream(
                    "POST",
                    f"{BASE_URL}/v1/chat/completions",
                    json=payload,
                    headers=auth_headers,
                ) as stream_resp:
                    stream_text = "".join(stream_resp.iter_text())
                    content_type = stream_resp.headers.get("content-type", "")
                    data_lines = [line for line in stream_text.splitlines() if line.startswith("data: ")]
                    has_done = any(line.strip() == "data: [DONE]" for line in data_lines)
                    has_metadata = any('"object":"chat.completion.metadata"' in line for line in data_lines) or any(
                        '"object": "chat.completion.metadata"' in line for line in data_lines
                    )

                    if (
                        stream_resp.status_code == 200
                        and "text/event-stream" in content_type
                        and len(data_lines) > 0
                        and has_done
                    ):
                        _pass("POST /v1/chat/completions (stream=true)")
                        if has_metadata:
                            _pass("stream metadata event detected")
                        else:
                            _warn("stream metadata event not found in this response")
                    else:
                        error_code = ""
                        try:
                            parsed = stream_resp.json()
                            error_code = parsed.get("error", {}).get("code", "")
                        except Exception:
                            error_code = ""
                        if error_code in {
                            "missing_api_key",
                            "invalid_api_key",
                            "all_providers_failed",
                            "provider_unavailable",
                            "stream_provider_failed",
                            "streaming_not_supported",
                        }:
                            _warn(
                                "POST /v1/chat/completions stream mode requires configured provider key/network. "
                                f"Current code: {error_code}"
                            )
                        else:
                            all_required_passed = False
                            _fail(
                                f"POST /v1/chat/completions stream -> "
                                f"{stream_resp.status_code} {stream_text[:300]}"
                            )
            except Exception as exc:
                all_required_passed = False
                _fail(f"POST /v1/chat/completions stream exception: {exc}")

    return 0 if all_required_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

