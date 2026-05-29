from __future__ import annotations

import json
import os
import sys

import httpx


def _metadata_summary(meta: dict) -> str:
    provider = meta.get("provider", "-")
    tools_used = meta.get("tools", {}).get("used", [])
    sources = meta.get("sources", [])
    redactions = meta.get("guard", {}).get("redaction_count", 0)
    return (
        f"provider={provider}, tools_used={len(tools_used)}, "
        f"sources={len(sources)}, redactions={redactions}"
    )


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
        "stream": True,
        "search": "off",
        "tools": "off",
    }

    metadata_event: dict | None = None
    got_done = False

    try:
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", f"{base_url}/v1/chat/completions", json=payload, headers=headers) as response:
                if response.status_code != 200:
                    raw = response.text
                    print(f"[ERROR] status={response.status_code}")
                    print(raw[:1000])
                    return 1

                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[len("data: ") :].strip()
                    if raw == "[DONE]":
                        got_done = True
                        break

                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    obj = event.get("object")
                    if obj == "chat.completion.chunk":
                        choices = event.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if isinstance(content, str) and content:
                                print(content, end="", flush=True)
                    elif obj == "chat.completion.metadata":
                        metadata_event = event
                    elif obj == "chat.completion.error":
                        err = event.get("error", {})
                        print("")
                        print(f"[STREAM ERROR] {err.get('code', 'unknown')}: {err.get('message', 'unknown error')}")
                        return 1
    except Exception as exc:
        print(f"[ERROR] stream request failed: {exc}")
        return 1

    print("")
    if metadata_event:
        print(f"[METADATA] {_metadata_summary(metadata_event)}")

    if not got_done:
        print("[ERROR] stream ended without [DONE]")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
