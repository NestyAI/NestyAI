from __future__ import annotations

from app.providers.constants import openai_compatible_chat_url, resolve_z_ai_base_url
from app.providers.openai_compatible import OpenAICompatibleChatProvider
from app.utils.logging import get_logger

logger = get_logger("nesty.providers.z_ai")


class ZAIProvider(OpenAICompatibleChatProvider):
    def __init__(self, api_key: str | None, timeout_seconds: float, base_url: str | None = None) -> None:
        if base_url and "api.z.ai" in str(base_url).lower():
            logger.warning(
                "z_ai_deprecated_base_url",
                extra={
                    "configured_base_url": str(base_url),
                    "using_base_url": resolve_z_ai_base_url(None),
                    "hint": "Remove Z_AI_BASE_URL from .env or set open.bigmodel.cn URL",
                },
            )
        normalized_base = resolve_z_ai_base_url(base_url)
        super().__init__(
            provider_name="z_ai",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            endpoint=openai_compatible_chat_url(normalized_base),
        )
