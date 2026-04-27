"""Slack message formatting utilities.

Converts agent output (Markdown) to Slack's mrkdwn format and handles
the character limit by uploading long responses as files.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Slack's hard limit for a text message is 40,000 characters, but practical
# readability drops well before that.  Responses beyond max_length are
# uploaded as a snippet instead.
_FILE_UPLOAD_SUFFIX = "\n_(Full response uploaded as a file above.)_"


def markdown_to_mrkdwn(text: str) -> str:
    """Convert basic Markdown to Slack mrkdwn format.

    Handles the most common patterns produced by LLM output.
    """
    # Bold: **text** or __text__ -> *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.DOTALL)

    # Italic: _text_ -> _text_  (already compatible)
    # Strikethrough: ~~text~~ -> ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text, flags=re.DOTALL)

    # Inline code: `code` stays as-is (Slack supports it)
    # Code blocks: ```lang\n...\n``` -> ```\n...\n```  (remove language hint)
    text = re.sub(r"```[a-zA-Z0-9_+-]*\n", "```\n", text)

    # Markdown links: [label](url) -> <url|label>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Headings: ## Heading -> *Heading*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    return text


def truncate(text: str, max_length: int) -> tuple[str, bool]:
    """Truncate text to max_length.

    Returns (possibly truncated text, was_truncated).
    """
    if len(text) <= max_length:
        return text, False
    truncated = text[:max_length] + "…"
    return truncated, True


async def post_response(
    *,
    client,
    channel: str,
    thread_ts: str,
    text: str,
    max_length: int,
) -> None:
    """Post agent output to a Slack thread, uploading as a file if too long."""
    formatted = markdown_to_mrkdwn(text)
    truncated, was_truncated = truncate(formatted, max_length)

    if was_truncated:
        # Upload full response as a file, then post a short notice
        try:
            await client.files_upload_v2(
                channel=channel,
                thread_ts=thread_ts,
                content=text,
                filename="response.md",
                title="Full investigation report",
            )
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=truncated + _FILE_UPLOAD_SUFFIX,
            )
            return
        except Exception:
            logger.exception("File upload failed, falling back to truncated message")

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=truncated,
    )
