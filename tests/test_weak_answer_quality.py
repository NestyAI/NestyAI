from __future__ import annotations

from app.core.answer_quality import (
    assess_quality_retry,
    detect_weak_answer,
    evaluate_answer_quality,
    is_safety_refusal,
    is_short_factual_answer,
)
from app.schemas.chat import GuardInfo, RetrievalInfo
from app.schemas.tools import SourceItem


def test_detect_weak_answer_flags_missing_info_despite_context() -> None:
    weak, reason = detect_weak_answer(
        "I don't have enough information to answer that question accurately.",
        context_available=True,
    )
    assert weak is True
    assert reason == "missing_info_despite_context"


def test_detect_weak_answer_ignores_short_factual_answer() -> None:
    assert is_short_factual_answer("42")
    weak, _reason = detect_weak_answer("42", context_available=True)
    assert weak is False


def test_detect_weak_answer_ignores_substantive_answer() -> None:
    answer = (
        "Based on the provided sources, FastAPI 0.115 added improved OpenAPI schema generation "
        "and several middleware fixes for streaming responses."
    )
    weak, _reason = detect_weak_answer(answer, context_available=True)
    assert weak is False


def test_is_safety_refusal_detects_policy_decline() -> None:
    assert is_safety_refusal("I can't help with creating malware or exploits.")


def test_assess_quality_retry_skips_safety_refusal() -> None:
    assessment = assess_quality_retry(
        "I can't help with that request because it violates my policy.",
        retrieval=RetrievalInfo(context_used=True, search_used=True),
        sources=[SourceItem(title="A", url="https://example.com/a", snippet="Snippet")],
    )
    assert assessment.should_retry is False


def test_assess_quality_retry_skips_output_redacted() -> None:
    assessment = assess_quality_retry(
        "",
        retrieval=RetrievalInfo(context_used=True, search_used=True),
        sources=[SourceItem(title="A", url="https://example.com/a", snippet="Snippet")],
        output_guard_info=GuardInfo(output_redacted=True, redaction_count=1),
    )
    assert assessment.should_retry is False


def test_assess_quality_retry_empty_with_context() -> None:
    assessment = assess_quality_retry(
        "",
        retrieval=RetrievalInfo(context_used=True, search_used=True),
        sources=[SourceItem(title="A", url="https://example.com/a", snippet="Snippet")],
    )
    assert assessment.should_retry is True
    assert assessment.retry_reason == "empty_answer"
    assert assessment.context_available is True


def test_assess_quality_retry_weak_with_context() -> None:
    assessment = assess_quality_retry(
        "I do not have enough information to answer.",
        retrieval=RetrievalInfo(context_used=True, search_used=True),
        sources=[SourceItem(title="A", url="https://example.com/a", snippet="Snippet")],
    )
    assert assessment.should_retry is True
    assert assessment.weak_answer_before_retry is True


def test_evaluate_answer_quality_sets_context_metadata() -> None:
    _text, info = evaluate_answer_quality(
        "A direct answer grounded in the provided context.",
        retrieval=RetrievalInfo(context_used=True, search_used=True),
        sources=[SourceItem(title="A", url="https://example.com/a", snippet="Snippet")],
    )
    assert info.context_available is True
    assert info.context_signal_count >= 1
