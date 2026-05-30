from __future__ import annotations

import argparse
import asyncio
import importlib


def test_semantic_recall_script_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.test_semantic_recall")
    assert callable(module.main)


def test_semantic_recall_script_reports_disabled(monkeypatch, capsys) -> None:
    module = importlib.import_module("scripts.test_semantic_recall")
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "embeddings_enabled": False,
                "semantic_recall_enabled": False,
                "semantic_recall_top_k": 5,
                "semantic_recall_min_score": 0.72,
            },
        )(),
    )
    args = argparse.Namespace(
        text="remember this",
        conversation_id=None,
        top_k=None,
        min_score=None,
        api_key_id=None,
    )
    code = asyncio.run(module._run(args))
    output = capsys.readouterr().out
    assert code == 0
    assert "status: embeddings_disabled" in output
