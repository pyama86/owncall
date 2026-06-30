"""Tests for mention handler helpers (ping short-circuit, namespace injection)."""

from owncall.handlers.mention import (
    _clean_mention_text,
    _inject_namespace_context,
    _is_ping,
)


class TestIsPing:
    def test_plain_ping(self):
        assert _is_ping("ping") is True

    def test_ping_with_punctuation(self):
        assert _is_ping("ping?") is True
        assert _is_ping("ping!") is True

    def test_case_insensitive(self):
        assert _is_ping("PING") is True
        assert _is_ping("Ping") is True

    def test_ignores_with_extra_content(self):
        assert _is_ping("ping foo") is False
        assert _is_ping("are you there ping") is False


class TestCleanMentionText:
    def test_removes_mention(self):
        assert _clean_mention_text("<@U12345> hello") == "hello"

    def test_strips_whitespace(self):
        assert _clean_mention_text("   <@U12345>   ping   ") == "ping"

    def test_defaults_to_greeting_when_empty(self):
        assert "Hello" in _clean_mention_text("<@U12345>")


class TestInjectNamespaceContext:
    def test_string_input(self):
        out = _inject_namespace_context("what is broken?", "production")
        assert isinstance(out, list)
        # Two synthetic ack messages + one user input
        assert len(out) == 3
        assert out[0]["role"] == "user"
        assert "production" in out[0]["content"]
        assert out[1]["role"] == "assistant"
        assert out[2]["content"] == "what is broken?"

    def test_injects_before_last_user_message(self):
        history = [
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
            {"role": "user", "content": "follow-up"},
        ]
        out = _inject_namespace_context(history, "staging")
        # 3 original + 2 synthetic = 5
        assert len(out) == 5
        # The static prefix (user history + assistant) stays at the head;
        # the namespace pair is inserted right before the latest user msg.
        assert out[0] == history[0]
        assert out[1] == history[1]
        assert out[2]["role"] == "user"
        assert "staging" in out[2]["content"]
        assert out[3]["role"] == "assistant"
        assert out[4] == history[2]

    def test_appends_when_no_user_message(self):
        history = [{"role": "assistant", "content": "system note"}]
        out = _inject_namespace_context(history, "qa")
        # No user message exists, so the namespace pair is appended at the tail.
        # Order: original assistant, synthetic user, synthetic assistant.
        assert len(out) == 3
        assert out[0] == history[0]
        assert out[1]["role"] == "user"
        assert "qa" in out[1]["content"]
        assert out[2]["role"] == "assistant"
