"""Tests for alert handler relay-to-response-channel logic."""

from unittest.mock import AsyncMock, MagicMock

from owncall.handlers.alert import _relay_alert_to_response_channel


class TestRelayAlertToResponseChannel:
    async def test_posts_permalink_to_response_channel(self):
        client = MagicMock()
        client.chat_getPermalink = AsyncMock(
            return_value={"permalink": "https://slack.com/archives/C123/p000001"}
        )
        client.chat_postMessage = AsyncMock(return_value={"ts": "111.222"})

        ts = await _relay_alert_to_response_channel(
            client,
            alert_channel="C_PUBLIC",
            alert_ts="000001",
            response_channel="C_PRIVATE",
        )

        assert ts == "111.222"
        client.chat_getPermalink.assert_called_once_with(
            channel="C_PUBLIC", message_ts="000001"
        )
        client.chat_postMessage.assert_called_once_with(
            channel="C_PRIVATE",
            text="Alert detected: https://slack.com/archives/C123/p000001",
        )

    async def test_returns_none_when_permalink_fails(self):
        client = MagicMock()
        client.chat_getPermalink = AsyncMock(side_effect=Exception("API error"))
        client.chat_postMessage = AsyncMock()

        ts = await _relay_alert_to_response_channel(
            client,
            alert_channel="C_PUBLIC",
            alert_ts="000001",
            response_channel="C_PRIVATE",
        )

        assert ts is None
        client.chat_postMessage.assert_not_called()

    async def test_returns_none_when_post_fails(self):
        client = MagicMock()
        client.chat_getPermalink = AsyncMock(
            return_value={"permalink": "https://slack.com/archives/C123/p000001"}
        )
        client.chat_postMessage = AsyncMock(side_effect=Exception("channel not found"))

        ts = await _relay_alert_to_response_channel(
            client,
            alert_channel="C_PUBLIC",
            alert_ts="000001",
            response_channel="C_PRIVATE",
        )

        assert ts is None
