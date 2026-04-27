"""Handler for Grafana/Prometheus alert messages.

Listens for all messages in channels the bot is in and auto-investigates
those that match the configured alert detection rules.

Skips:
- Messages posted by the bot itself (prevents feedback loops).
- Thread replies (only root messages trigger auto-investigation; subsequent
  replies in the alert thread are handled via @mention).
- Messages in channels not listed in alert_detection.channels (when the
  list is non-empty).
"""

from __future__ import annotations

import asyncio
import logging

from agents import Runner

from owncall.config import AppConfig
from owncall.util.alert_detect import extract_alert_summary, is_alert_message
from owncall.util.slack_format import post_response

logger = logging.getLogger(__name__)

# Limit concurrent auto-investigations to avoid overwhelming the LLM API
# and Grafana MCP server during alert storms.
_INVESTIGATION_SEMAPHORE = asyncio.Semaphore(3)

_INVESTIGATION_PROMPT_TEMPLATE = """\
An alert was posted in Slack:

{summary}

Please investigate this alert using the available MCP tools.
Identify the likely root cause and suggest remediation steps.
"""


def register_alert_handler(app, agent, bot_user_id: str, cfg: AppConfig) -> None:
    """Register the message event handler for alert detection.

    Uses @app.event("message") instead of @app.message() so that messages
    with subtypes (e.g. bot_message) are also captured and acknowledged,
    preventing Bolt from returning 404 "unhandled request" for those events.
    """

    @app.event("message")
    async def handle_possible_alert(body: dict, client, logger=logger) -> None:
        message = body.get("event", {})

        # Skip thread replies — only root messages trigger auto-investigation
        if message.get("thread_ts") and message["thread_ts"] != message.get("ts"):
            return

        # Skip messages from the bot itself to prevent feedback loops
        if _is_own_message(message, bot_user_id):
            return

        # Skip plain human messages (no bot_id and no subtype)
        if not message.get("bot_id") and not message.get("subtype"):
            return

        # Optionally restrict to configured channels
        channel = message.get("channel", "")
        if cfg.alert_detection.channels and channel not in cfg.alert_detection.channels:
            return

        if not is_alert_message(message, cfg.alert_detection):
            return

        event_ts = message["ts"]

        try:
            await client.reactions_add(
                channel=channel,
                timestamp=event_ts,
                name="mag",
            )
        except Exception:
            logger.debug("Could not add investigation reaction", exc_info=True)

        async with _INVESTIGATION_SEMAPHORE:
            try:
                summary = extract_alert_summary(message)
                prompt = _INVESTIGATION_PROMPT_TEMPLATE.format(summary=summary)

                logger.info("Auto-investigating alert in %s/%s", channel, event_ts)
                result = await Runner.run(agent, prompt)

                await post_response(
                    client=client,
                    channel=channel,
                    thread_ts=event_ts,
                    text=result.final_output,
                    max_length=cfg.response.max_length,
                )
            except Exception:
                logger.exception("Error investigating alert in %s/%s", channel, event_ts)
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=event_ts,
                    text=":warning: Failed to investigate this alert automatically.",
                )
            finally:
                try:
                    await client.reactions_remove(
                        channel=channel,
                        timestamp=event_ts,
                        name="mag",
                    )
                except Exception:
                    logger.debug("Could not remove investigation reaction", exc_info=True)
                try:
                    await client.reactions_add(
                        channel=channel,
                        timestamp=event_ts,
                        name=cfg.response.reaction_on_complete,
                    )
                except Exception:
                    logger.debug("Could not add complete reaction", exc_info=True)


def _is_own_message(message: dict, bot_user_id: str) -> bool:
    return message.get("user") == bot_user_id
