"""Handler for Slack Block Kit interactive actions.

Currently handles:

- ``select_namespace``: user picks a namespace from the dropdown presented by
  the mention handler when the agent asks for namespace information.
"""

from __future__ import annotations

import asyncio
import logging

from owncall.agent import AgentBundle
from owncall.config import AppConfig
from owncall.context.thread import ThreadContextManager
from owncall.util.cost import format_usage_footer
from owncall.util.judge_runner import run_agent_with_judge
from owncall.util.slack_format import post_response

logger = logging.getLogger(__name__)


def register_block_action_handlers(
    app,
    bundle: AgentBundle,
    thread_ctx: ThreadContextManager,
    cfg: AppConfig,
) -> None:
    """Register Block Kit action handlers on the given Slack AsyncApp."""

    @app.action("select_namespace")
    async def handle_namespace_selection(ack, body: dict, client, logger=logger) -> None:
        # Acknowledge immediately to satisfy Slack's 3-second timeout
        await ack()

        # Extract channel before try so it is always available in the finally block
        channel: str = body["channel"]["id"]

        try:
            selected: str = body["actions"][0]["selected_option"]["value"]
            msg = body["message"]
            thread_ts: str = msg.get("thread_ts") or msg["ts"]

            logger.info("Namespace selected: %s in %s/%s", selected, channel, thread_ts)

            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"▶ namespace: *{selected}*",
            )

            input_list = await thread_ctx.build_input_list(channel, thread_ts)
            input_list.append({"role": "user", "content": f"namespace: {selected}"})

            await client.reactions_add(
                channel=channel,
                timestamp=msg["ts"],
                name=cfg.response.reaction_on_start,
            )

            judged = await asyncio.wait_for(
                run_agent_with_judge(
                    bundle.primary,
                    input_list,
                    max_turns=cfg.agent.max_turns,
                    judge_cfg=cfg.judge,
                ),
                timeout=cfg.agent.run_timeout_seconds,
            )

            footer = (
                format_usage_footer(judged.raw_result, cfg.llm.pricing)
                if cfg.response.cost_footer and not judged.blocked
                else ""
            )

            await post_response(
                client=client,
                channel=channel,
                thread_ts=thread_ts,
                text=judged.final_output,
                max_length=cfg.response.max_length,
                footer=footer,
            )

        except TimeoutError:
            logger.warning(
                "Block-action agent run timed out after %.1fs",
                cfg.agent.run_timeout_seconds,
            )

        except Exception:
            logger.exception("Error handling namespace selection in body: %s", body)

        finally:
            try:
                await client.reactions_add(
                    channel=channel,
                    timestamp=body["message"]["ts"],
                    name=cfg.response.reaction_on_complete,
                )
            except Exception:
                logger.debug("Could not add complete reaction", exc_info=True)
