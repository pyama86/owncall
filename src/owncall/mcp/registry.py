"""Build MCP server instances from config.

Each server is an async context manager. Callers should use
``contextlib.AsyncExitStack`` to manage their lifetimes together.

Two compression layers are wired in when ``compression.enabled=True``:

1. Deterministic JSON minify (and optional Loki shrink) via
   :func:`owncall.mcp.compress.apply_compression`, attached to every server
   regardless of tool_compression to take advantage of the free byte savings.
2. LLM-based summarisation via :class:`owncall.mcp.compression.CompressingMCPServer`,
   only when ``tool_compression.enabled`` is True.  This wraps the server
   after the deterministic layer so the summariser sees the smallest possible
   input.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.mcp import MCPServerSse, MCPServerStdio, create_static_tool_filter
from agents.mcp.server import MCPServer

# MCPServerStreamableHttp was added in a later release of openai-agents.
# Import it conditionally so the package still works with older versions.
try:
    from agents.mcp import MCPServerStreamableHttp

    _streamable_http_available = True
except ImportError:
    MCPServerStreamableHttp = None  # type: ignore[assignment,misc]
    _streamable_http_available = False

from owncall.config import MCPServerConfig, ToolCompressionConfig
from owncall.mcp.compress import apply_compression
from owncall.mcp.compression import CompressingMCPServer, Summarizer

logger = logging.getLogger(__name__)

# Use the abstract base type so the alias also covers ``CompressingMCPServer``.
AnyMCPServer = MCPServer


def build_mcp_servers(
    configs: list[MCPServerConfig],
    compression: ToolCompressionConfig | None = None,
) -> list[MCPServer]:
    """Instantiate enabled MCP servers from configuration.

    Servers whose ``enabled`` flag is False or whose URL/command is empty
    are silently skipped so that optional integrations (e.g. GitHub MCP)
    can be gated on environment variables without causing startup failures.
    """
    servers: list[MCPServer] = []
    summarizer: Summarizer | None = None

    if compression is not None and compression.enabled:
        if compression.summarize_threshold_chars > 0:
            try:
                summarizer = Summarizer(compression)
                logger.info(
                    "Tool compression enabled: model=%s threshold=%d max_chars=%d",
                    compression.summarize_model,
                    compression.summarize_threshold_chars,
                    compression.max_tool_result_chars,
                )
            except Exception:
                # OpenAI SDK missing or API key absent: keep going in
                # truncate-only mode rather than failing startup.
                logger.exception("Failed to build Summarizer; falling back to truncate-only")
        else:
            logger.info(
                "Tool compression enabled (truncate-only): max_chars=%d",
                compression.max_tool_result_chars,
            )

    for cfg in configs:
        if not cfg.enabled:
            logger.info("MCP server '%s' is disabled, skipping", cfg.name)
            continue

        server = _create_server(cfg)
        if server is None:
            continue
        _wrap_call_tool_with_compression(server, compression)

        if compression is not None and compression.enabled:
            server = CompressingMCPServer(server, compression, summarizer)
        servers.append(server)
        logger.info("Registered MCP server '%s' (%s)", cfg.name, cfg.type)

    return servers


def _wrap_call_tool_with_compression(
    server: Any, compression: ToolCompressionConfig | None
) -> None:
    """Monkey-patch ``server.call_tool`` so its result goes through
    :func:`apply_compression` before being returned.

    The wrap is always applied because :func:`apply_compression` is safe and
    pass-through on parse errors.  Loki shrink only fires when the
    deployment opts into it by setting drop labels/fields.
    """
    original = server.call_tool

    loki_tools = compression.loki_tools if compression is not None else ("query_loki_logs",)
    drop_labels = compression.loki_drop_stream_labels if compression is not None else ()
    drop_body = compression.loki_drop_log_body_fields if compression is not None else ()

    async def call_tool_compressed(
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        result = await original(tool_name, arguments, meta=meta)
        return apply_compression(
            result,
            tool_name,
            loki_tools=loki_tools,
            loki_drop_stream_labels=drop_labels,
            loki_drop_log_body_fields=drop_body,
        )

    server.call_tool = call_tool_compressed  # type: ignore[method-assign]


def _build_tool_filter(cfg: MCPServerConfig):
    """Build a static tool filter from ``allowed_tools`` / ``blocked_tools``.

    Returns ``None`` when both lists are empty so the SDK exposes every tool.
    When both lists are populated the SDK applies ``allowed`` first and then
    removes anything in ``blocked``.
    """
    if not cfg.allowed_tools and not cfg.blocked_tools:
        return None
    return create_static_tool_filter(
        allowed_tool_names=cfg.allowed_tools or None,
        blocked_tool_names=cfg.blocked_tools or None,
    )


def _create_server(cfg: MCPServerConfig) -> MCPServer | None:
    server_type = cfg.type.lower()
    tool_filter = _build_tool_filter(cfg)
    if tool_filter is not None:
        logger.info(
            "MCP server '%s' tool filter: allowed=%d blocked=%d",
            cfg.name,
            len(cfg.allowed_tools),
            len(cfg.blocked_tools),
        )

    if server_type == "sse":
        if not cfg.url:
            logger.warning("MCP server '%s' has no URL, skipping", cfg.name)
            return None
        params: dict[str, Any] = {
            "url": cfg.url,
            "timeout": cfg.timeout,
            "sse_read_timeout": cfg.sse_read_timeout,
        }
        if cfg.headers:
            params["headers"] = cfg.headers
        return MCPServerSse(
            name=cfg.name,
            params=params,
            cache_tools_list=cfg.cache_tools,
            client_session_timeout_seconds=cfg.client_session_timeout_seconds,
            max_retry_attempts=cfg.max_retry_attempts,
            retry_backoff_seconds_base=cfg.retry_backoff_seconds_base,
            tool_filter=tool_filter,
        )

    if server_type in ("streamable_http", "streamable-http"):
        if not _streamable_http_available:
            logger.warning(
                "MCP server '%s': streamable_http transport requires a newer version of "
                "openai-agents. Skipping.",
                cfg.name,
            )
            return None
        if not cfg.url:
            logger.warning("MCP server '%s' has no URL, skipping", cfg.name)
            return None
        params = {
            "url": cfg.url,
            "timeout": cfg.timeout,
            "sse_read_timeout": cfg.sse_read_timeout,
        }
        if cfg.headers:
            params["headers"] = cfg.headers
        return MCPServerStreamableHttp(
            name=cfg.name,
            params=params,
            cache_tools_list=cfg.cache_tools,
            client_session_timeout_seconds=cfg.client_session_timeout_seconds,
            max_retry_attempts=cfg.max_retry_attempts,
            retry_backoff_seconds_base=cfg.retry_backoff_seconds_base,
            tool_filter=tool_filter,
        )

    if server_type == "stdio":
        if not cfg.command:
            logger.warning("MCP server '%s' has no command, skipping", cfg.name)
            return None
        return MCPServerStdio(
            name=cfg.name,
            params={"command": cfg.command[0], "args": cfg.command[1:]},
            cache_tools_list=cfg.cache_tools,
            client_session_timeout_seconds=cfg.client_session_timeout_seconds,
            max_retry_attempts=cfg.max_retry_attempts,
            retry_backoff_seconds_base=cfg.retry_backoff_seconds_base,
            tool_filter=tool_filter,
        )

    logger.warning("Unknown MCP server type '%s' for '%s', skipping", cfg.type, cfg.name)
    return None
