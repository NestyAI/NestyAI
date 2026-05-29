from __future__ import annotations

from app.guards.input_guard import InputGuard
from app.schemas.chat import ChatMessage


def test_input_guard_redacts_sensitive_data_and_preserves_order() -> None:
    guard = InputGuard()
    messages = [
        ChatMessage(role="user", content="my key sk-ABCDEFGHIJKLMNOPQRSTUV123456"),
        ChatMessage(role="assistant", content="groq gsk_ABCDEFGHIJKLMNOPQRSTUV123456"),
        ChatMessage(role="user", content="openrouter sk-or-v1-ABCDEFGHIJKLMNOPQRSTUV123456"),
        ChatMessage(role="user", content="google AIzaSyD1234567890ABCDEFGHIJKL"),
        ChatMessage(role="user", content="github ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"),
        ChatMessage(role="user", content="jwt eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.xyz"),
        ChatMessage(role="user", content="Bearer token: Bearer abc.def.ghi"),
        ChatMessage(role="user", content="password=super-secret"),
        ChatMessage(role="user", content="api_key=abc123secret"),
        ChatMessage(role="user", content="db postgres://user:pass@localhost:5432/mydb"),
        ChatMessage(
            role="user",
            content="-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----",
        ),
        ChatMessage(role="user", content="email me at user@example.com"),
        ChatMessage(role="user", content="phone +84901234567"),
        ChatMessage(role="user", content=r"path C:\Users\ADMIN\secret.txt"),
        ChatMessage(role="user", content="unix /home/admin/.ssh/id_rsa"),
    ]

    safe_messages, metadata = guard.scan_messages(messages)

    assert [m.role for m in safe_messages] == [m.role for m in messages]
    assert metadata.input_redacted is True
    assert metadata.redaction_count > 0
    assert len(metadata.categories) > 0

    redacted_text = "\n".join(message.content for message in safe_messages)
    originals = [
        "sk-ABCDEFGHIJKLMNOPQRSTUV123456",
        "gsk_ABCDEFGHIJKLMNOPQRSTUV123456",
        "sk-or-v1-ABCDEFGHIJKLMNOPQRSTUV123456",
        "AIzaSyD1234567890ABCDEFGHIJKL",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.xyz",
        "Bearer abc.def.ghi",
        "password=super-secret",
        "api_key=abc123secret",
        "postgres://user:pass@localhost:5432/mydb",
        "BEGIN PRIVATE KEY",
        "user@example.com",
        "+84901234567",
        r"C:\Users\ADMIN\secret.txt",
        "/home/admin/.ssh/id_rsa",
    ]
    for original in originals:
        assert original not in redacted_text

