"""Handler for @mention events.

When a user @mentions the bot, this handler:

1. Short-circuits trivial pings back to ``pong`` without consulting the LLM.
2. Adds a reaction to acknowledge receipt.
3. Builds conversation history from the Slack thread (if it's a reply) and
   injects channel-pinned namespace context near the latest user message
   (keeps the prompt-cache-friendly prefix intact).
4. Runs the agent under a wall-clock timeout and posts the result back.
5. If the response asks for namespace selection, fetches available namespaces
   from Grafana via the investigator agent and appends a Block Kit selector.
6. Updates the reaction on completion.
"""

from __future__ import annotations

import asyncio
import logging
import re

from owncall.agent import AgentBundle
from owncall.config import AppConfig
from owncall.context.thread import ThreadContextManager
from owncall.util.cost import format_usage_footer
from owncall.util.interactive import (
    build_namespace_selector_blocks,
    fetch_namespaces,
    is_asking_for_namespace,
)
from owncall.util.judge_runner import run_agent_with_judge
from owncall.util.slack_format import post_response

logger = logging.getLogger(__name__)

_PING_INPUTS = frozenset({"ping", "ping?", "ping!"})


def register_mention_handler(
    app, bundle: AgentBundle, thread_ctx: ThreadContextManager, cfg: AppConfig
) -> None:
    """Register the app_mention event handler on the given Slack AsyncApp."""

    @app.event("app_mention")
    async def handle_mention(event: dict, client, logger=logger) -> None:
        channel = event["channel"]
        event_ts = event["ts"]
        thread_ts = event.get("thread_ts", event_ts)

        if cfg.mention.channels and channel not in cfg.mention.channels:
            logger.debug("Ignoring mention in non-configured channel %s", channel)
            return

        cleaned_text = _clean_mention_text(event.get("text", ""))

        # Short-circuit ping: do not burn LLM tokens on connectivity checks.
        if _is_ping(cleaned_text):
            try:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="pong",
                )
            except Exception:
                logger.debug("Could not respond to ping", exc_info=True)
            return

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
                    input_data = cleaned_text
            else:
                input_data = cleaned_text

            namespace = cfg.channel_namespace_map.get(channel)
            if namespace:
                input_data = _inject_namespace_context(input_data, namespace)

            logger.info("Running agent for mention in %s/%s", channel, thread_ts)
            judged = await asyncio.wait_for(
                run_agent_with_judge(
                    bundle.primary,
                    input_data,
                    max_turns=cfg.agent.max_turns,
                    judge_cfg=cfg.judge,
                ),
                timeout=cfg.agent.run_timeout_seconds,
            )
            response_text = judged.final_output

            footer = (
                format_usage_footer(judged.raw_result, cfg.llm.pricing)
                if cfg.response.cost_footer and not judged.blocked
                else ""
            )

            await post_response(
                client=client,
                channel=channel,
                thread_ts=thread_ts,
                text=response_text,
                max_length=cfg.response.max_length,
                footer=footer,
            )

            # When the agent is asking for namespace, fetch candidates via
            # the investigator (the one that holds MCP servers) and present
            # a Block Kit selector so the user can pick without typing.
            # Skip when the run was blocked by Judge — the agent never
            # actually answered, so the question detection is meaningless.
            if not judged.blocked and is_asking_for_namespace(response_text) and not namespace:
                namespaces = await fetch_namespaces(bundle.investigator, cfg.agent.max_turns)
                if namespaces:
                    blocks = build_namespace_selector_blocks(namespaces)
                    await client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        blocks=blocks,
                        text="Namespace を選択してください",
                    )

        except TimeoutError:
            logger.warning(
                "Agent run timed out after %.1fs in %s/%s",
                cfg.agent.run_timeout_seconds,
                channel,
                thread_ts,
            )
            try:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=":hourglass_flowing_sand: The investigation timed out."
                    " Please narrow the question and try again.",
                )
            except Exception:
                logger.debug("Could not post timeout notice", exc_info=True)

        except Exception:
            logger.exception("Error handling mention in %s/%s", channel, thread_ts)
            try:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=":warning: An error occurred while processing your request."
                    " Please try again.",
                )
            except Exception:
                logger.debug("Could not post error notice", exc_info=True)

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


def _is_ping(text: str) -> bool:
    return text.strip().lower() in _PING_INPUTS


def _inject_namespace_context(input_data: str | list[dict], namespace: str) -> list[dict]:
    """Prepend namespace context so the agent uses the correct namespace.

    The hint is inserted immediately before the most recent user message
    rather than at the very top of the input list.  The OpenAI prompt cache
    is matched from the prefix, so putting per-channel namespace text at the
    head invalidates the static system prompt / tool definition cache.
    Keeping the historical messages first and the channel-specific hint at
    the tail preserves the cache key for the static prefix.
    """
    prefix = [
        {
            "role": "user",
            "content": (
                f"The Kubernetes namespace for this channel is: {namespace}."
                " Use it as the default namespace."
            ),
        },
        {
            "role": "assistant",
            "content": (
                f"Understood. I will use '{namespace}' as the default namespace"
                " for this conversation."
            ),
        },
    ]
    if isinstance(input_data, str):
        return prefix + [{"role": "user", "content": input_data}]

    # Find the index of the most recent user message; inject the hint right
    # before it so the static prefix remains cache-stable.
    last_user_idx = len(input_data)
    for idx in range(len(input_data) - 1, -1, -1):
        if input_data[idx].get("role") == "user":
            last_user_idx = idx
            break
    return list(input_data[:last_user_idx]) + prefix + list(input_data[last_user_idx:])
