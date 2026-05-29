from __future__ import annotations

import json
import os
import sys

import httpx


def main() -> int:
    base_url = os.getenv("NESTY_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key = os.getenv("NESTY_API_KEY", "").strip()
    model = os.getenv("NESTY_MODEL", "nesty-combined-1.0").strip()

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Write a short intro about NestyAI."}],
        "stream": False,
        "search": "off",
        "tools": "off",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{base_url}/v1/chat/completions", json=payload, headers=headers)
    except Exception as exc:
        print(f"[ERROR] request failed: {exc}")
        return 1

    if response.status_code != 200:
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}
        print(f"[ERROR] status={response.status_code}")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 1

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        print("[ERROR] unexpected response format")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 1

    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
