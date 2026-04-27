"""Handler for @mention events.

When a user @mentions the bot, this handler:
1. Adds a reaction to acknowledge receipt.
2. Builds conversation history from the Slack thread (if it's a reply).
3. Strips the bot mention from the user's text.
4. Runs the agent and posts the result back in the thread.
5. If the agent response asks for namespace selection, fetches available
   namespaces from Grafana and appends a Block Kit selector to the reply.
6. Updates the reaction on completion.
"""

from __future__ import annotations

import logging
import re

from agents import Runner

from owncall.config import AppConfig
from owncall.context.thread import ThreadContextManager
from owncall.util.interactive import (
    build_namespace_selector_blocks,
    fetch_namespaces,
    is_asking_for_namespace,
)
from owncall.util.slack_format import post_response

logger = logging.getLogger(__name__)


def register_mention_handler(app, agent, thread_ctx: ThreadContextManager, cfg: AppConfig) -> None:
    """Register the app_mention event handler on the given Slack AsyncApp."""

    @app.event("app_mention")
    async def handle_mention(event: dict, client, logger=logger) -> None:
        channel = event["channel"]
        event_ts = event["ts"]
        thread_ts = event.get("thread_ts", event_ts)

        try:
            await client.reactions_add(
                channel=channel,
                timestamp=event_ts,
                name=cfg.response.reaction_on_start,
            )
        except Exception:
            logger.debug("Could not add start reaction", exc_info=True)

        try:
            if event.get("thread_ts"):
                input_data = await thread_ctx.build_input_list(channel, thread_ts)
                if not input_data:
                    input_data = _clean_mention_text(event.get("text", ""))
            else:
                input_data = _clean_mention_text(event.get("text", ""))

            logger.info("Running agent for mention in %s/%s", channel, thread_ts)
            result = await Runner.run(agent, input_data)
            response_text = result.final_output

            # Post the agent's text response first
            await post_response(
                client=client,
                channel=channel,
                thread_ts=thread_ts,
                text=response_text,
                max_length=cfg.response.max_length,
            )

            # When the agent is asking for namespace, fetch candidates from Grafana
            # and present a Block Kit selector so the user can pick without typing.
            if is_asking_for_namespace(response_text):
                namespaces = await fetch_namespaces(agent)
                if namespaces:
                    blocks = build_namespace_selector_blocks(namespaces)
                    await client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        blocks=blocks,
                        text="Namespace を選択してください",  # fallback for notifications
                    )

        except Exception:
            logger.exception("Error handling mention in %s/%s", channel, thread_ts)
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=":warning: An error occurred while processing your request. Please try again.",
            )
        finally:
            try:
                await client.reactions_remove(
                    channel=channel,
                    timestamp=event_ts,
                    name=cfg.response.reaction_on_start,
                )
            except Exception:
                logger.debug("Could not remove start reaction", exc_info=True)
            try:
                await client.reactions_add(
                    channel=channel,
                    timestamp=event_ts,
                    name=cfg.response.reaction_on_complete,
                )
            except Exception:
                logger.debug("Could not add complete reaction", exc_info=True)


def _clean_mention_text(text: str) -> str:
    """Remove bot @mentions from the text and return a clean query string."""
    cleaned = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    return cleaned if cleaned else "Hello! How can I help you?"
