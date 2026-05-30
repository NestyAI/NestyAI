from __future__ import annotations

import argparse
import asyncio
import importlib
import json


def test_semantic_recall_eval_script_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.evaluate_semantic_recall")
    assert callable(module.main)


def test_semantic_recall_eval_script_reports_disabled_with_guidance(monkeypatch, capsys) -> None:
    module = importlib.import_module("scripts.evaluate_semantic_recall")
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "embeddings_enabled": False,
                "semantic_recall_scope": "conversation",
                "semantic_recall_top_k": 5,
                "semantic_recall_min_score": 0.72,
                "embeddings_provider": "openrouter",
                "embeddings_model": "embed",
                "model_dump": lambda self: {},
            },
        )(),
    )
    args = argparse.Namespace(
        query="hello",
        conversation_id=None,
        scope="conversation",
        top_k=None,
        min_score=None,
        show_content_preview=False,
        json=False,
    )
    code = asyncio.run(module._run(args))
    out = capsys.readouterr().out
    assert code == 0
    assert "status: embeddings_disabled" in out
    assert "EMBEDDINGS_ENABLED=true" in out


def test_semantic_recall_eval_script_json_output(monkeypatch, capsys) -> None:
    module = importlib.import_module("scripts.evaluate_semantic_recall")
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "embeddings_enabled": True,
                "semantic_recall_scope": "conversation",
                "semantic_recall_top_k": 5,
                "semantic_recall_min_score": 0.72,
                "embeddings_provider": "openrouter",
                "embeddings_model": "embed",
                "model_dump": lambda self: {
                    "semantic_recall_scope": "conversation",
                    "semantic_recall_top_k": 5,
                    "semantic_recall_min_score": 0.72,
                },
            },
        )(),
    )
    monkeypatch.setattr(module, "count_embedding_records", lambda: 3)

    async def _mock_retrieve(**kwargs):
        return {
            "reason": "semantic_recall_enabled",
            "matches": [
                {
                    "message_id": "msg_1",
                    "conversation_id": "conv_1",
                    "role": "user",
                    "score": 0.88,
                    "pinned": True,
                    "excluded": False,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "content": "secret",
                }
            ],
            "pinned_matches_count": 1,
            "excluded_matches_count": 0,
            "deduped_count": 0,
            "candidate_count": 5,
            "max_score": 0.88,
            "min_returned_score": 0.88,
        }

    monkeypatch.setattr(module, "retrieve_semantic_memories", _mock_retrieve)
    args = argparse.Namespace(
        query="what did I say?",
        conversation_id="conv_1",
        scope="conversation",
        top_k=5,
        min_score=0.7,
        show_content_preview=True,
        json=True,
    )
    code = asyncio.run(module._run(args))
    out = capsys.readouterr().out.strip()
    assert code == 0
    payload = json.loads(out)
    assert payload["matches_count"] == 1
    assert payload["matches"][0]["message_id"] == "msg_1"
    assert len(payload["matches"][0]["preview"]) <= 303
