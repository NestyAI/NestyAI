from __future__ import annotations

from app.core.context_assembler import assemble_hybrid_context, build_context_item


def test_context_assembler_prioritizes_pinned_items_and_dedupes_exact_duplicates() -> None:
    items = [
        build_context_item(source="semantic_recall", content="Ordinary memory", score=0.8),
        build_context_item(source="fts", content="Pinned memory block", pinned=True, score=0.1),
        build_context_item(source="semantic_recall", content="Pinned memory block", pinned=True, score=0.2),
        build_context_item(
            source="semantic_recall",
            content="Pinned memory block with a little more detail that should remain.",
            score=0.15,
        ),
    ]

    result = assemble_hybrid_context(items, summary_text="Unrelated summary", budget_chars=2000)

    assert result.items[0].pinned is True
    assert result.items[0].source == "semantic_recall"
    assert result.items[1].pinned is False
    assert result.items[-1].content.endswith("should remain.")
    assert result.context_text.count("Pinned memory block") == 2
    assert "little more detail" in result.context_text


def test_context_assembler_keeps_detailed_evidence_even_when_summary_overlaps() -> None:
    summary_text = "We discussed the rollback plan and the fallback timeline."
    items = [
        build_context_item(
            source="semantic_recall",
            content="We discussed the rollback plan and the fallback timeline.",
            score=0.9,
        ),
        build_context_item(
            source="semantic_recall",
            content="We discussed the rollback plan and the fallback timeline, plus two concrete implementation risks.",
            score=0.8,
        ),
    ]

    result = assemble_hybrid_context(items, summary_text=summary_text, budget_chars=2000)

    assert "plus two concrete implementation risks" in result.context_text
    assert "rollback plan and the fallback timeline." not in result.context_text
    assert result.context_items_count == 1


def test_context_assembler_prioritizes_high_score_search_and_tool_items() -> None:
    items = [
        build_context_item(
            source="semantic_recall",
            content="Generic memory context without specific release details.",
            score=0.4,
        ),
        build_context_item(
            source="search",
            content="Release notes: streaming reliability improved in version 0.115.",
            score=0.9,
        ),
        build_context_item(
            source="tools",
            content="Tool result: package version 0.115.0 confirmed.",
            score=0.95,
        ),
    ]

    result = assemble_hybrid_context(items, summary_text="", budget_chars=260)

    assert result.items[0].source == "tools"
    assert "0.115.0" in result.context_text
    assert "streaming reliability improved" in result.context_text


def test_context_assembler_truncates_to_budget() -> None:
    items = [
        build_context_item(
            source="semantic_recall",
            content="This is a very long retrieval block. " * 40,
            score=0.9,
        )
    ]

    result = assemble_hybrid_context(items, summary_text="", budget_chars=220)

    assert result.context_truncated is True
    assert result.context_used_chars <= result.context_budget_chars
    assert len(result.context_text) <= result.context_budget_chars
