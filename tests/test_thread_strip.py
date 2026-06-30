"""Tests for the cost-footer stripping done before re-injecting bot history."""

from owncall.context.thread import _strip_bot_metadata


class TestStripBotMetadata:
    def test_removes_cost_footer(self):
        text = (
            "Here is the report.\n"
            "Line two.\n"
            "_:money_with_wings: 1,234 tokens · in 800 / out 434 · 3 calls_"
        )
        out = _strip_bot_metadata(text)
        assert "money_with_wings" not in out
        assert "Here is the report." in out
        assert "Line two." in out

    def test_leaves_text_without_footer(self):
        text = "Just a normal response."
        assert _strip_bot_metadata(text) == text

    def test_handles_only_footer(self):
        text = "_:money_with_wings: 100 tokens · 1 calls_"
        # Footer pattern requires a leading newline; bare footer is not stripped.
        # Whichever the regex picks, the function must not crash.
        assert isinstance(_strip_bot_metadata(text), str)

    def test_strips_trailing_whitespace(self):
        text = "Body\n\n_:money_with_wings: 50 tokens · 1 calls_   \n"
        out = _strip_bot_metadata(text)
        assert out == "Body"
