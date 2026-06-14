from __future__ import annotations

BUILTIN_PROVIDER_IDS: frozenset[str] = frozenset(
    {
        "groq",
        "openrouter",
        "nvidia",
        "ollama_cloud",
        "deepseek",
        "openai",
        "mistral",
        "z_ai",
        "google_gemini",
        "anthropic_claude",
    }
)

# Built-in provider endpoints (hardcoded defaults — only API keys required in env/Console).
# Override base URLs via env only for: NVIDIA_BASE_URL, OLLAMA_BASE_URL (optional), Z_AI_BASE_URL (optional).

GROQ_CHAT_COMPLETIONS_URL: str = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_CHAT_COMPLETIONS_URL: str = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_CLOUD_DEFAULT_BASE_URL: str = "https://ollama.com"

OPENAI_CHAT_COMPLETIONS_URL: str = "https://api.openai.com/v1/chat/completions"
MISTRAL_CHAT_COMPLETIONS_URL: str = "https://api.mistral.ai/v1/chat/completions"
DEEPSEEK_CHAT_COMPLETIONS_URL: str = "https://api.deepseek.com/v1/chat/completions"

# Zhipu AI (智谱) OpenAI-compatible — https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
Z_AI_DEFAULT_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
# GLM Coding Plan only — optional override via Z_AI_BASE_URL
Z_AI_CODING_BASE_URL: str = "https://open.bigmodel.cn/api/coding/paas/v4"

GEMINI_API_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
ANTHROPIC_MESSAGES_URL: str = "https://api.anthropic.com/v1/messages"


def openai_compatible_chat_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def resolve_z_ai_base_url(base_url: str | None) -> str:
    """Return Zhipu OpenAI-compatible base URL; ignore deprecated api.z.ai overrides."""
    candidate = str(base_url or Z_AI_DEFAULT_BASE_URL).rstrip("/")
    if "api.z.ai" in candidate.lower():
        return Z_AI_DEFAULT_BASE_URL.rstrip("/")
    return candidate
