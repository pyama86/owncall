"""LLM-based MCP tool response compression (``CompressingMCPServer``).

The deterministic layer in :mod:`owncall.mcp.compress` removes whitespace and
known noisy fields, but heavy observability tools (Loki, Prometheus, GitHub
search) can still return tens or hundreds of kilobytes per call.  Across a
30-turn investigation these accumulate in the agent's input history and
inflate cost.

``CompressingMCPServer`` wraps another ``MCPServer`` and, on ``call_tool``,

1. Passes through results at or below ``summarize_threshold_chars``.
2. Tries to summarise larger results with a cheap model.
3. Falls back to truncation when the summary is unavailable or fails to
   shrink the input by at least ``min_reduction_ratio``.

The summariser uses the raw OpenAI chat completion API (not ``Runner.run``)
so its token usage does not get attributed to the parent agent run.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from agents.mcp.server import MCPServer
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    TextContent,
)
from mcp.types import Tool as MCPTool

from owncall.config import ToolCompressionConfig

if TYPE_CHECKING:  # avoid runtime import cycle with agents
    from agents.agent import AgentBase
    from agents.run_context import RunContextWrapper

logger = logging.getLogger(__name__)

_SUMMARIZED_HEADER = "[owncall-compressed: summarized by cheap model]"
_TRUNCATED_HEADER = "[owncall-compressed: truncated to fit context budget]"
_TRUNCATED_SUFFIX = (
    "\n\n…(remaining output truncated to fit the context budget;"
    " narrow the query and retry to see more)"
)


def _content_text_length(content: list[Any]) -> int:
    """Sum the lengths of every text content block; image/audio blocks ignored."""
    total = 0
    for block in content:
        if getattr(block, "type", "") == "text":
            text = getattr(block, "text", "") or ""
            total += len(text)
    return total


def _concat_text_blocks(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", "") == "text":
            text = getattr(block, "text", "") or ""
            parts.append(text)
    return "\n".join(parts)


def _replace_text_with(content: list[Any], new_text: str) -> list[Any]:
    """Replace all text blocks with a single ``TextContent``; keep non-text blocks."""
    non_text = [b for b in content if getattr(b, "type", "") != "text"]
    return [TextContent(type="text", text=new_text), *non_text]


class Summarizer:
    """Calls a cheap model to compress a tool result into a brief factual summary.

    Uses the OpenAI Python SDK directly (``chat.completions.create``) rather
    than going through ``Runner.run`` so the compression turn is not counted
    against the parent agent's usage.  ``openai`` is imported lazily so this
    module can still be imported in environments without the SDK installed.
    """

    def __init__(self, cfg: ToolCompressionConfig) -> None:
        self._cfg = cfg
        from openai import AsyncOpenAI  # local import: optional dependency

        self._client = AsyncOpenAI()

    async def summarize(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        raw_text: str,
    ) -> str | None:
        """Return the compressed text, or ``None`` on failure (fail-open).

        The caller falls back to truncation on ``None`` so a transient LLM
        outage cannot break the underlying tool call.
        """
        try:
            args_text = json.dumps(arguments or {}, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            args_text = str(arguments)

        user_content = (
            "## tool\n"
            f"{tool_name}\n\n"
            "## arguments\n"
            f"```json\n{args_text}\n```\n\n"
            "## raw response\n"
            f"```\n{raw_text}\n```\n"
        )

        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._cfg.summarize_model,
                    messages=[
                        {"role": "system", "content": self._cfg.summarize_system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                ),
                timeout=self._cfg.summarize_timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "compression summarize timeout: tool=%s timeout=%.1fs",
                tool_name,
                self._cfg.summarize_timeout_seconds,
            )
            return None
        except Exception:
            logger.exception("compression summarize failed: tool=%s", tool_name)
            return None

        choices = getattr(response, "choices", None) or []
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if not isinstance(content, str) or not content.strip():
            return None
        return content.strip()


class CompressingMCPServer(MCPServer):
    """Wrap an ``MCPServer`` and compress oversized ``call_tool`` responses.

    Only ``call_tool`` is intercepted; every other method is forwarded to the
    inner server unchanged.  ``__getattr__`` exposes implementation-specific
    attributes (such as ``tool_filter``) so external code that inspects the
    inner server continues to work through the wrapper.
    """

    def __init__(
        self,
        inner: MCPServer,
        cfg: ToolCompressionConfig,
        summarizer: Summarizer | None = None,
    ) -> None:
        super().__init__()
        self._inner = inner
        self._cfg = cfg
        # ``summarize_threshold_chars=0`` requests truncate-only mode; skip
        # the summariser instance entirely so we never call the cheap model.
        self._summarizer: Summarizer | None = (
            summarizer if cfg.summarize_threshold_chars > 0 else None
        )

    # --- delegation ---

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def cached_tools(self) -> list[MCPTool] | None:
        return self._inner.cached_tools

    async def connect(self) -> None:
        await self._inner.connect()

    async def cleanup(self) -> None:
        await self._inner.cleanup()

    async def __aenter__(self) -> CompressingMCPServer:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self._inner.__aexit__(exc_type, exc_value, traceback)

    async def list_tools(
        self,
        run_context: RunContextWrapper[Any] | None = None,
        agent: AgentBase | None = None,
    ) -> list[MCPTool]:
        return await self._inner.list_tools(run_context, agent)

    async def list_prompts(self) -> ListPromptsResult:
        return await self._inner.list_prompts()

    async def get_prompt(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> GetPromptResult:
        return await self._inner.get_prompt(name, arguments)

    async def list_resources(self, cursor: str | None = None) -> ListResourcesResult:
        return await self._inner.list_resources(cursor)

    async def list_resource_templates(
        self, cursor: str | None = None
    ) -> ListResourceTemplatesResult:
        return await self._inner.list_resource_templates(cursor)

    async def read_resource(self, uri: str) -> ReadResourceResult:
        return await self._inner.read_resource(uri)

    def __getattr__(self, item: str) -> Any:
        # ``self._inner`` was set in __init__, so this never recurses; access
        # the underlying ``__dict__`` directly to avoid hitting __getattr__.
        try:
            inner = self.__dict__["_inner"]
        except KeyError as e:  # pragma: no cover - guarded by __init__
            raise AttributeError(item) from e
        return getattr(inner, item)

    # --- compression ---

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> CallToolResult:
        result = await self._inner.call_tool(tool_name, arguments, meta)
        return await self._maybe_compress(result, tool_name, arguments)

    async def _maybe_compress(
        self,
        result: CallToolResult,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> CallToolResult:
        # Errors are short and worth showing in full; never compress them.
        if result.isError:
            return result

        total = _content_text_length(result.content)
        threshold = self._cfg.summarize_threshold_chars
        max_chars = self._cfg.max_tool_result_chars

        needs_summarize = self._summarizer is not None and threshold > 0 and total > threshold
        needs_truncate = total > max_chars
        if not needs_summarize and not needs_truncate:
            return result

        raw_text = _concat_text_blocks(result.content)

        if needs_summarize:
            assert self._summarizer is not None
            summary = await self._summarizer.summarize(tool_name, arguments, raw_text)
            if summary is not None:
                reduction = 1.0 - (len(summary) / max(1, len(raw_text)))
                if reduction < self._cfg.min_reduction_ratio:
                    logger.info(
                        "compression summary not short enough: tool=%s raw=%d summary=%d "
                        "reduction=%.2f (min=%.2f), falling back to truncate",
                        tool_name,
                        len(raw_text),
                        len(summary),
                        reduction,
                        self._cfg.min_reduction_ratio,
                    )
                else:
                    final = self._cap(f"{_SUMMARIZED_HEADER}\n{summary}", max_chars)
                    logger.info(
                        "compression summarize: tool=%s raw=%d summary=%d final=%d",
                        tool_name,
                        len(raw_text),
                        len(summary),
                        len(final),
                    )
                    return self._replace(result, final)
            else:
                logger.info(
                    "compression summarize unavailable, falling back to truncate: tool=%s raw=%d",
                    tool_name,
                    len(raw_text),
                )

        truncated = self._truncate(raw_text, max_chars)
        logger.info(
            "compression truncate: tool=%s raw=%d truncated=%d",
            tool_name,
            len(raw_text),
            len(truncated),
        )
        return self._replace(result, truncated)

    @staticmethod
    def _cap(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - len(_TRUNCATED_SUFFIX)] + _TRUNCATED_SUFFIX

    @staticmethod
    def _truncate(raw_text: str, max_chars: int) -> str:
        head = f"{_TRUNCATED_HEADER}\n"
        budget = max_chars - len(head) - len(_TRUNCATED_SUFFIX)
        if budget <= 0:
            # Fail-safe for absurdly small max_chars settings.
            return head + _TRUNCATED_SUFFIX
        if len(raw_text) <= budget:
            return head + raw_text
        return head + raw_text[:budget] + _TRUNCATED_SUFFIX

    @staticmethod
    def _replace(result: CallToolResult, new_text: str) -> CallToolResult:
        new_content = _replace_text_with(result.content, new_text)
        return CallToolResult(
            content=new_content,
            structuredContent=None,
            isError=result.isError,
        )
