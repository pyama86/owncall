"""Deterministic MCP tool response compression.

Two layers are applied in order:

1. **JSON minify** — every tool response that parses as JSON is re-serialised
   without whitespace.  Safe (pass-through on parse errors) and typically
   saves 20–40% of bytes that would otherwise become input tokens every turn.
2. **Loki structural shrink** — for tools that return Loki ``query_range``
   responses we drop noisy stream labels and per-log fields that the operator
   has flagged as redundant via configuration.  Both lists default to empty
   so this layer is opt-in.

Compression happens before any LLM-based compression in
:mod:`owncall.mcp.compression` so the summarizer sees the smallest possible
input.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)


def minify_json(text: str) -> str:
    """Re-serialise JSON text without whitespace.

    Pass-through on parse failure or empty input so this is safe to apply
    unconditionally.
    """
    if not text:
        return text
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def shrink_loki_response(
    text: str,
    *,
    drop_stream_labels: Iterable[str] = (),
    drop_log_body_fields: Iterable[str] = (),
) -> str:
    """Strip configured labels / fields from a Loki ``query_range`` response.

    Expected structure (Loki HTTP API ``query_range`` compatible)::

        {"status": "success",
         "data": {"resultType": "streams",
                  "result": [{"stream": {...labels}, "values": [[ts, body], ...]}]}}

    When the structure does not match the response is left untouched (still
    minified by :func:`minify_json`).
    """
    drop_labels = set(drop_stream_labels)
    drop_body_fields = set(drop_log_body_fields)

    if not drop_labels and not drop_body_fields:
        return minify_json(text)

    try:
        root = json.loads(text)
    except (ValueError, TypeError):
        return text

    result = None
    if isinstance(root, dict):
        data = root.get("data")
        if isinstance(data, dict):
            result = data.get("result")

    if isinstance(result, list):
        for stream_obj in result:
            if not isinstance(stream_obj, dict):
                continue
            stream = stream_obj.get("stream")
            if isinstance(stream, dict) and drop_labels:
                for key in drop_labels:
                    stream.pop(key, None)
            values = stream_obj.get("values")
            if isinstance(values, list) and drop_body_fields:
                for entry in values:
                    if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[1], str):
                        entry[1] = _shrink_log_body(entry[1], drop_body_fields)

    return json.dumps(root, separators=(",", ":"), ensure_ascii=False)


def _shrink_log_body(text: str, drop_fields: set[str]) -> str:
    """Drop configured top-level fields from a JSON-serialised log line."""
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(obj, dict):
        return text
    for key in drop_fields:
        obj.pop(key, None)
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def apply_compression(
    result: Any,
    tool_name: str,
    *,
    loki_tools: Iterable[str] = ("query_loki_logs",),
    loki_drop_stream_labels: Iterable[str] = (),
    loki_drop_log_body_fields: Iterable[str] = (),
) -> Any:
    """Compress text blocks inside a ``CallToolResult`` in place.

    Returns the same ``result`` object with each text content block's ``.text``
    replaced by its compressed form when a smaller version was produced.
    """
    content = getattr(result, "content", None)
    if not content:
        return result

    loki_set = frozenset(loki_tools)

    for block in content:
        text = getattr(block, "text", None)
        if not isinstance(text, str) or not text:
            continue

        if tool_name in loki_set:
            compressed = shrink_loki_response(
                text,
                drop_stream_labels=loki_drop_stream_labels,
                drop_log_body_fields=loki_drop_log_body_fields,
            )
        else:
            compressed = minify_json(text)

        if len(compressed) < len(text):
            saved = len(text) - len(compressed)
            pct = saved * 100 // len(text)
            logger.info(
                "mcp_compress: tool=%s before=%d after=%d saved=%d (-%d%%)",
                tool_name,
                len(text),
                len(compressed),
                saved,
                pct,
            )
            block.text = compressed
    return result
