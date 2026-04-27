"""Tests for thread conversation context manager."""

import pytest

from owncall.context.thread import _message_role


class TestMessageRole:
    def test_bot_message_by_bot_id(self):
        msg = {"bot_id": "B123", "text": "I investigated..."}
        assert _message_role(msg, "U_BOT") == "assistant"

    def test_bot_message_by_user_id(self):
        msg = {"user": "U_BOT", "text": "I investigated..."}
        assert _message_role(msg, "U_BOT") == "assistant"

    def test_human_message(self):
        msg = {"user": "U_HUMAN", "text": "What is wrong?"}
        assert _message_role(msg, "U_BOT") == "user"

    def test_no_user_or_bot_id(self):
        msg = {"text": "system message"}
        assert _message_role(msg, "U_BOT") == "user"
