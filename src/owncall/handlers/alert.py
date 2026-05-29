"""Handler for Grafana/Prometheus alert messages.

Listens for all messages in channels the bot is in and auto-investigates
those that match the configured alert detection rules.

Skips:
- Messages posted by the bot itself (prevents feedback loops).
- Thread replies (only root messages trigger auto-investigation; subsequent
  replies in the alert thread are handled via @mention).
- Messages in channels not listed in alert_detection.channels (when the
  list is non-empty).

When alert_detection.response_channel is set, investigation results are
posted to that channel (e.g. a private channel) instead of the alert's
original channel. A link to the original alert is posted first so that
the response thread is traceable back to the source.
"""

from __future__ import annotations

import asyncio
import logging

from agents import Runner

from owncall.config import AppConfig
from owncall.util.alert_dedup import AlertDeduplicator
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

    dedup_cfg = cfg.alert_detection.dedup
    deduplicator: AlertDeduplicator | None = (
        AlertDeduplicator(ttl_seconds=dedup_cfg.ttl_seconds) if dedup_cfg.enabled else None
    )

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

        # Deduplicate similar alerts within the TTL window
        summary = extract_alert_summary(message)
        if deduplicator and deduplicator.is_duplicate(summary, channel):
            logger.info("Skipping duplicate alert in %s/%s", channel, event_ts)
            try:
                await client.reactions_add(
                    channel=channel,
                    timestamp=event_ts,
                    name=dedup_cfg.reaction,
                )
            except Exception:
                logger.debug("Could not add dedup reaction", exc_info=True)
            return

        if deduplicator:
            deduplicator.record(summary, channel)

        try:
            await client.reactions_add(
                channel=channel,
                timestamp=event_ts,
                name="mag",
            )
        except Exception:
            logger.debug("Could not add investigation reaction", exc_info=True)

        # When response_channel is configured, relay the alert link there and
        # post investigation results in that channel's thread instead.
        # This allows owncall responses to be confined to a private channel
        # even when alerts arrive in public channels.
        configured_response_channel = cfg.alert_detection.response_channel
        if configured_response_channel:
            relay_ts = await _relay_alert_to_response_channel(
                client, channel, event_ts, configured_response_channel
            )
            post_channel = configured_response_channel if relay_ts else channel
            post_ts = relay_ts if relay_ts else event_ts
        else:
            post_channel = channel
            post_ts = event_ts

        async with _INVESTIGATION_SEMAPHORE:
            try:
                prompt = _INVESTIGATION_PROMPT_TEMPLATE.format(summary=summary)
                namespace = cfg.channel_namespace_map.get(channel)
                if namespace:
                    prompt += f"\nThe Kubernetes namespace for this channel is: {namespace}\n"

                logger.info("Auto-investigating alert in %s/%s", channel, event_ts)
                result = await Runner.run(agent, prompt, max_turns=cfg.agent.max_turns)

                await post_response(
                    client=client,
                    channel=post_channel,
                    thread_ts=post_ts,
                    text=result.final_output,
                    max_length=cfg.response.max_length,
                )
            except Exception:
                logger.exception("Error investigating alert in %s/%s", channel, event_ts)
                await client.chat_postMessage(
                    channel=post_channel,
                    thread_ts=post_ts,
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


async def _relay_alert_to_response_channel(
    client, alert_channel: str, alert_ts: str, response_channel: str
) -> str | None:
    """Post a permalink to the alert in response_channel.

    Returns the ts of the relay message so the investigation result can be
    threaded under it, or None if posting failed.
    """
    try:
        permalink_result = await client.chat_getPermalink(
            channel=alert_channel, message_ts=alert_ts
        )
        permalink = permalink_result["permalink"]
    except Exception:
        logger.warning(
            "Could not get alert permalink for %s/%s", alert_channel, alert_ts, exc_info=True
        )
        return None

    try:
        result = await client.chat_postMessage(
            channel=response_channel,
            text=f"Alert detected: {permalink}",
        )
        return result["ts"]
    except Exception:
        logger.warning(
            "Could not post alert link to response channel %s", response_channel, exc_info=True
        )
        return None


def _is_own_message(message: dict, bot_user_id: str) -> bool:
    return message.get("user") == bot_user_id
