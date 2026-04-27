"""Main application: assembles MCP servers, agent, and Slack app.

Startup order:
1. Load config
2. Open MCP server connections (async context managers via AsyncExitStack)
3. Build the agent with active MCP servers
4. Create Slack AsyncApp and register event handlers
5. Start Socket Mode handler (blocks until shutdown)

Shutdown unwinds in reverse, closing MCP connections cleanly.
"""

from __future__ import annotations

import contextlib
import logging

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from owncall.agent import create_agent
from owncall.config import AppConfig
from owncall.context.thread import ThreadContextManager
from owncall.handlers.alert import register_alert_handler
from owncall.handlers.block_action import register_block_action_handlers
from owncall.handlers.mention import register_mention_handler
from owncall.mcp.registry import build_mcp_servers

logger = logging.getLogger(__name__)


async def run_bot(config: AppConfig) -> None:
    """Start the OwnCall Slack bot."""

    # Build MCP server instances from config (disabled servers are excluded)
    server_instances = build_mcp_servers(config.mcp_servers)

    if not server_instances:
        logger.warning(
            "No MCP servers are enabled. The agent will have no tools available."
        )

    # Open all MCP server connections and keep them alive for the bot lifetime
    async with contextlib.AsyncExitStack() as stack:
        active_servers = []
        for server in server_instances:
            connected = await stack.enter_async_context(server)
            active_servers.append(connected)
            logger.info("Connected to MCP server '%s'", server.name)

        # Build the agent with all connected MCP servers
        agent = create_agent(config.llm, config.agent, active_servers)
        logger.info(
            "Agent created with model=%s and %d MCP server(s)",
            config.llm.model,
            len(active_servers),
        )

        # Create the Slack app
        slack_app = AsyncApp(token=config.slack.bot_token)

        # Resolve the bot's own user ID (needed for thread context role mapping
        # and to prevent the bot from responding to its own alert messages)
        auth_resp = await slack_app.client.auth_test()
        bot_user_id: str = auth_resp["user_id"]
        logger.info("Authenticated as bot user %s", bot_user_id)

        thread_ctx = ThreadContextManager(slack_app.client, bot_user_id)

        # Register event handlers
        register_mention_handler(slack_app, agent, thread_ctx, config)
        register_alert_handler(slack_app, agent, bot_user_id, config)
        register_block_action_handlers(slack_app, agent, thread_ctx, config)

        # Start Socket Mode (blocks until SIGINT/SIGTERM)
        handler = AsyncSocketModeHandler(slack_app, config.slack.app_token)
        logger.info("Starting Socket Mode handler…")
        await handler.start_async()
