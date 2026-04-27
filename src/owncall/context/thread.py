"""Thread conversation history management.

Slack threads are the source of truth for conversation history.
On each mention within a thread, we fetch the full reply history from
the Slack API and convert it into the input format expected by the
openai-agents Runner, so the agent has full context without requiring
a persistent store.
"""

from __future__ import annotations

import logging

from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Maximum number of thread messages to include in the context window.
# Older messages are dropped to avoid exceeding token limits.
_MAX_THREAD_MESSAGES = 50


class ThreadContextManager:
    def __init__(self, client: AsyncWebClient, bot_user_id: str) -> None:
        self._client = client
        self._bot_user_id = bot_user_id

    async def build_input_list(self, channel: str, thread_ts: str) -> list[dict]:
        """Return the thread history as an openai-agents input list.

        Each message becomes a dict with ``role`` (user/assistant) and
        ``content``.  The most recent ``_MAX_THREAD_MESSAGES`` are kept.
        """
        try:
            response = await self._client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=_MAX_THREAD_MESSAGES,
            )
        except Exception:
            logger.exception("Failed to fetch thread history for %s/%s", channel, thread_ts)
            return []

        messages = response.get("messages", [])

        input_list = []
        for msg in messages:
            role = _message_role(msg, self._bot_user_id)
            text = msg.get("text", "").strip()
            if text:
                input_list.append({"role": role, "content": text})

        return input_list


def _message_role(msg: dict, bot_user_id: str) -> str:
    """Return 'assistant' for bot messages, 'user' for everything else."""
    if msg.get("bot_id") or msg.get("user") == bot_user_id:
        return "assistant"
    return "user"
