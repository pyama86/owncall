"""Handler for Slack Block Kit interactive actions.

Currently handles:
- select_namespace: user picks a namespace from the dropdown presented by the
  mention handler when the agent asks for namespace information.
"""

from __future__ import annotations

import logging

from agents import Runner

from owncall.config import AppConfig
from owncall.context.thread import ThreadContextManager
from owncall.util.slack_format import post_response

logger = logging.getLogger(__name__)


def register_block_action_handlers(
    app,
    agent,
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
            # The selector message may itself be in a thread; use thread_ts when present
            thread_ts: str = msg.get("thread_ts") or msg["ts"]

            logger.info(
                "Namespace selected: %s in %s/%s", selected, channel, thread_ts
            )

            # Post the selection visibly so the thread history reflects what was chosen
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"▶ namespace: *{selected}*",
            )

            # Build full thread history, then append the selection as user input
            # so the agent treats it as a reply to its own clarifying question.
            input_list = await thread_ctx.build_input_list(channel, thread_ts)
            input_list.append({"role": "user", "content": f"namespace: {selected}"})

            await client.reactions_add(
                channel=channel,
                timestamp=msg["ts"],
                name=cfg.response.reaction_on_start,
            )

            result = await Runner.run(agent, input_list)

            await post_response(
                client=client,
                channel=channel,
                thread_ts=thread_ts,
                text=result.final_output,
                max_length=cfg.response.max_length,
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
