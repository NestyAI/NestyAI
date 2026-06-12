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
