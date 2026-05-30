from __future__ import annotations

import importlib


def test_create_api_key_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.create_api_key")
    assert callable(module.main)


def test_list_api_keys_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.list_api_keys")
    assert callable(module.main)


def test_revoke_api_key_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.revoke_api_key")
    assert callable(module.main)


def test_usage_summary_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.usage_summary")
    assert callable(module.main)


def test_rebuild_fts_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.rebuild_fts")
    assert callable(module.main)


def test_rebuild_embeddings_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.rebuild_embeddings")
    assert callable(module.main)


def test_test_embedding_provider_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.test_embedding_provider")
    assert callable(module.main)


def test_test_semantic_recall_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.test_semantic_recall")
    assert callable(module.main)


def test_evaluate_semantic_recall_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.evaluate_semantic_recall")
    assert callable(module.main)


def test_cleanup_memory_module_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.cleanup_memory")
    assert callable(module.main)


def test_list_render_does_not_expose_key_hash() -> None:
    module = importlib.import_module("scripts.list_api_keys")
    lines = module.render_api_key_lines(
        [
            {
                "id": "key_123",
                "name": "dev",
                "key_prefix": "nsk_dev_abcd",
                "key_hash": "sha256:secret",
                "environment": "dev",
                "is_active": True,
                "daily_limit": None,
                "monthly_limit": None,
                "allowed_models": ["nesty-flash-1.0"],
                "created_at": "2026-01-01T00:00:00+00:00",
                "last_used_at": None,
            }
        ]
    )
    joined = "\n".join(lines)
    assert "key_hash" not in joined
    assert "sha256:secret" not in joined
