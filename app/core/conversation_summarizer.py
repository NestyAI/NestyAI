from __future__ import annotations

from typing import Any

from app.core.errors import APIError
from app.deps import get_guard_rules
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatMessage
from app.storage.conversations import (
    get_conversation,
    get_conversation_summary,
    get_message_count,
    get_messages_after_summary,
    update_conversation_summary,
)
from app.utils.ids import generate_request_id
from app.utils.logging import get_logger, log_safe


logger = get_logger("nesty.summary")


def should_summarize(conversation: dict[str, Any] | None, total_message_count: int, config: Any) -> bool:
    if not getattr(config, "conversation_summary_enabled", True):
        return False
    if conversation is None or conversation.get("archived_at"):
        return False
    if total_message_count < max(1, int(getattr(config, "conversation_summary_trigger_messages", 30))):
        return False
    summarized_count = int(conversation.get("summary_message_count") or 0)
    keep_recent = max(1, int(getattr(config, "conversation_summary_keep_recent_messages", 12)))
    unsummarized_count = max(0, int(total_message_count) - summarized_count)
    return unsummarized_count > keep_recent


def build_summary_prompt(existing_summary: str | None, older_messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    transcript_lines: list[str] = []
    for item in older_messages:
        role = str(item.get("role", "unknown"))
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        transcript_lines.append(f"{role}: {content}")
    transcript = "\n".join(transcript_lines) if transcript_lines else "(no content)"

    existing = existing_summary.strip() if existing_summary else "(none)"
    instruction = (
        "You are compressing internal chat history for session continuity.\n"
        "Write a concise summary with these sections:\n"
        "1) Session Summary\n"
        "2) User Preferences (only from this conversation)\n"
        "3) Decisions Made\n"
        "4) Unresolved Tasks\n"
        "5) Facts Needed for Future Turns\n\n"
        "Rules:\n"
        "- Do not include secrets, API keys, passwords, tokens, or sensitive personal data.\n"
        "- Keep it factual, compact, and useful for later turns.\n"
        "- If data is uncertain, mark it as uncertain.\n"
    )
    user_content = (
        f"Existing summary:\n{existing}\n\n"
        f"Older conversation messages to compress:\n{transcript}\n\n"
        "Return only the updated summary text."
    )
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": user_content},
    ]


async def summarize_conversation(
    conversation_id: str,
    router,
    config: Any,
    api_key_context: Any = None,
    force: bool = False,
    raise_on_error: bool = False,
) -> str | None:
    del api_key_context  # reserved for future ownership/audit extension

    db_path = str(getattr(config, "nesty_db_path", "data/nesty.db"))
    conversation = get_conversation(conversation_id, db_path=db_path)
    if conversation is None:
        return None

    total_message_count = get_message_count(conversation_id, db_path=db_path)
    if total_message_count <= 0:
        return None

    if not force and not should_summarize(conversation, total_message_count, config):
        return None

    current_summary = get_conversation_summary(conversation_id, db_path=db_path) or {}
    summarized_count = int(current_summary.get("summary_message_count") or 0)
    keep_recent = max(1, int(getattr(config, "conversation_summary_keep_recent_messages", 12)))

    unsummarized_messages = get_messages_after_summary(
        conversation_id=conversation_id,
        summary_message_count=summarized_count,
        limit=0,
        db_path=db_path,
    )
    if len(unsummarized_messages) <= keep_recent:
        if not force:
            return None
    if force and len(unsummarized_messages) <= 0:
        return None

    older_messages = (
        unsummarized_messages if force and len(unsummarized_messages) <= keep_recent
        else unsummarized_messages[: len(unsummarized_messages) - keep_recent]
    )
    if not older_messages:
        return None

    prompt = build_summary_prompt(str(current_summary.get("summary") or ""), older_messages)
    prompt_messages = [ChatMessage(role=item["role"], content=item["content"]) for item in prompt]

    try:
        result = await router.route_chat(
            request_id=generate_request_id(),
            model_alias=str(getattr(config, "conversation_summary_model", "nesty-flash-1.0")),
            messages=prompt_messages,
            temperature=0.2,
            max_tokens=800,
        )
    except APIError:
        log_safe(
            logger,
            "conversation_summary_failed",
            conversation_id=conversation_id,
            error_code="conversation_summary_failed",
        )
        if raise_on_error:
            raise
        return None
    except Exception:
        log_safe(
            logger,
            "conversation_summary_failed",
            conversation_id=conversation_id,
            error_code="conversation_summary_failed",
        )
        if raise_on_error:
            raise
        return None

    summary_text = (result.provider_result.content or "").strip()
    if not summary_text:
        return None

    guard = OutputGuard(rules=get_guard_rules())
    sanitized_summary, _guard_meta, _output_safety = guard.scan_text(summary_text)
    max_chars = max(1, int(getattr(config, "conversation_summary_max_chars", 4000)))
    if len(sanitized_summary) > max_chars:
        sanitized_summary = sanitized_summary[:max_chars].rstrip()

    new_summary_count = summarized_count + len(older_messages)
    updated = update_conversation_summary(
        conversation_id=conversation_id,
        summary=sanitized_summary,
        summary_message_count=new_summary_count,
        db_path=db_path,
    )
    if not updated:
        return None
    return sanitized_summary
