"""Utilities for Slack Block Kit interactive messages.

Detects when the agent is asking for structured input (e.g. namespace selection)
and builds the corresponding Block Kit payloads.
"""

from __future__ import annotations

import logging
import re

from agents import Runner

logger = logging.getLogger(__name__)

# Keywords that indicate the agent is asking the user to specify a namespace.
_NAMESPACE_QUESTION_PATTERNS = [
    r"namespace",
    r"ネームスペース",
    r"\bns\b",
    r"名前空間",
]

_NAMESPACE_RE = re.compile(
    "|".join(_NAMESPACE_QUESTION_PATTERNS),
    re.IGNORECASE,
)

_FETCH_NAMESPACES_PROMPT = (
    "Using the Grafana MCP tools, fetch the list of values for the Loki label "
    "'namespace'. Return ONLY a newline-separated list of namespace names with "
    "no extra text, headers, or explanation."
)


def is_asking_for_namespace(text: str) -> bool:
    """Return True when the agent response asks the user to specify a namespace."""
    return bool(_NAMESPACE_RE.search(text)) and "?" in text


async def fetch_namespaces(agent, max_turns: int = 30) -> list[str]:
    """Run a lightweight agent query to retrieve Loki namespace label values.

    Returns an empty list when the query fails or produces no recognisable output.
    """
    try:
        result = await Runner.run(agent, _FETCH_NAMESPACES_PROMPT, max_turns=max_turns)
        raw = result.final_output.strip()
        namespaces = [line.strip() for line in raw.splitlines() if line.strip()]
        return namespaces
    except Exception:
        logger.warning("Failed to fetch namespaces from Grafana MCP", exc_info=True)
        return []


def build_namespace_selector_blocks(namespaces: list[str]) -> list[dict]:
    """Build Block Kit blocks containing a static_select for namespace selection.

    Slack limits static_select to 100 options; we cap at 100 and sort
    alphabetically so the list is easy to scan.
    """
    sorted_ns = sorted(namespaces)[:100]
    options = [
        {
            "text": {"type": "plain_text", "text": ns, "emoji": False},
            "value": ns,
        }
        for ns in sorted_ns
    ]
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Namespace を選択してください:*"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "static_select",
                    "placeholder": {"type": "plain_text", "text": "namespace を選択…"},
                    "options": options,
                    "action_id": "select_namespace",
                }
            ],
        },
    ]
