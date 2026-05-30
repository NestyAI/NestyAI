from __future__ import annotations

from app.config import load_models_config
from app.core.model_behavior import apply_behavior_defaults, get_behavior_profile
from app.schemas.chat import ChatCompletionRequest, ChatMessage


def test_model_behavior_profiles_loaded() -> None:
    config = load_models_config()
    flash = config.models["nesty-flash-1.0"].model_dump()
    combined = config.models["nesty-combined-1.0"].model_dump()
    pro = config.models["nesty-pro-1.0"].model_dump()

    flash_profile = get_behavior_profile("nesty-flash-1.0", flash)
    combined_profile = get_behavior_profile("nesty-combined-1.0", combined)
    pro_profile = get_behavior_profile("nesty-pro-1.0", pro)

    assert flash_profile["behavior_profile"] == "flash"
    assert flash_profile["response_style"] == "concise"
    assert flash_profile["reasoning_depth"] == "low"

    assert combined_profile["behavior_profile"] == "balanced"
    assert combined_profile["reasoning_depth"] == "medium"

    assert pro_profile["behavior_profile"] == "pro"
    assert pro_profile["orchestration_enabled"] is True


def test_behavior_defaults_apply_when_request_omits_temperature_and_max_tokens() -> None:
    config = load_models_config()
    flash_cfg = config.models["nesty-flash-1.0"].model_dump()
    request = ChatCompletionRequest(
        model="nesty-flash-1.0",
        messages=[ChatMessage(role="user", content="quick summary")],
        search="off",
        tools="off",
    )
    defaults = apply_behavior_defaults(request, flash_cfg)
    assert defaults["temperature"] == 0.6
    assert defaults["max_tokens"] == 1024


def test_request_values_override_behavior_defaults() -> None:
    config = load_models_config()
    pro_cfg = config.models["nesty-pro-1.0"].model_dump()
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="deep answer")],
        temperature=1.2,
        max_tokens=555,
        search="off",
        tools="off",
    )
    defaults = apply_behavior_defaults(request, pro_cfg)
    assert defaults["temperature"] == 1.2
    assert defaults["max_tokens"] == 555
