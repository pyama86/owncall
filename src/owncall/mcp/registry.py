"""Build MCP server instances from config.

Each server is an async context manager. Callers should use
contextlib.AsyncExitStack to manage their lifetimes together.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.mcp import MCPServerSse, MCPServerStdio, MCPServerStreamableHttp

from owncall.config import MCPServerConfig

logger = logging.getLogger(__name__)

# Type alias for any supported MCP server variant
AnyMCPServer = MCPServerSse | MCPServerStreamableHttp | MCPServerStdio


def build_mcp_servers(configs: list[MCPServerConfig]) -> list[AnyMCPServer]:
    """Instantiate enabled MCP servers from configuration.

    Servers whose ``enabled`` flag is False or whose URL/command is empty
    are silently skipped so that optional integrations (e.g. GitHub MCP)
    can be gated on environment variables without causing startup failures.
    """
    servers: list[AnyMCPServer] = []

    for cfg in configs:
        if not cfg.enabled:
            logger.info("MCP server '%s' is disabled, skipping", cfg.name)
            continue

        server = _create_server(cfg)
        if server is None:
            continue
        servers.append(server)
        logger.info("Registered MCP server '%s' (%s)", cfg.name, cfg.type)

    return servers


def _create_server(cfg: MCPServerConfig) -> AnyMCPServer | None:
    server_type = cfg.type.lower()

    if server_type == "sse":
        if not cfg.url:
            logger.warning("MCP server '%s' has no URL, skipping", cfg.name)
            return None
        params: dict[str, Any] = {"url": cfg.url}
        if cfg.headers:
            params["headers"] = cfg.headers
        return MCPServerSse(
            name=cfg.name,
            params=params,
            cache_tools_list=cfg.cache_tools,
        )

    if server_type in ("streamable_http", "streamable-http"):
        if not cfg.url:
            logger.warning("MCP server '%s' has no URL, skipping", cfg.name)
            return None
        params = {"url": cfg.url}
        if cfg.headers:
            params["headers"] = cfg.headers
        return MCPServerStreamableHttp(
            name=cfg.name,
            params=params,
            cache_tools_list=cfg.cache_tools,
        )

    if server_type == "stdio":
        if not cfg.command:
            logger.warning("MCP server '%s' has no command, skipping", cfg.name)
            return None
        return MCPServerStdio(
            name=cfg.name,
            params={"command": cfg.command[0], "args": cfg.command[1:]},
            cache_tools_list=cfg.cache_tools,
        )

    logger.warning("Unknown MCP server type '%s' for '%s', skipping", cfg.type, cfg.name)
    return None
