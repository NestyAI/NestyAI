from __future__ import annotations

from app.tools.search_intent import should_use_search


def test_search_intent_explicit_modes() -> None:
    model_cfg = {"search_mode": "auto"}
    assert should_use_search("anything", model_cfg, explicit_search_mode="off") is False
    assert should_use_search("anything", model_cfg, explicit_search_mode="on") is True


def test_search_intent_model_off() -> None:
    assert should_use_search("latest weather", {"search_mode": "off"}, explicit_search_mode="auto") is False


def test_search_intent_auto_true_cases() -> None:
    model_cfg = {"search_mode": "auto"}
    assert should_use_search("Tin mới nhất về Groq Cloud hôm nay là gì?", model_cfg) is True
    assert should_use_search("What is the current price of Bitcoin?", model_cfg) is True
    assert should_use_search("latest version of FastAPI", model_cfg) is True
    assert should_use_search("thời tiết hôm nay", model_cfg) is True


def test_search_intent_auto_false_cases() -> None:
    model_cfg = {"search_mode": "auto"}
    assert should_use_search("Viết một đoạn giới thiệu về NestyAI", model_cfg) is False
    assert should_use_search("Dịch câu này sang tiếng Anh", model_cfg) is False
    assert should_use_search("Tóm tắt đoạn văn sau", model_cfg) is False
    assert should_use_search("Hello, how are you?", model_cfg) is False

