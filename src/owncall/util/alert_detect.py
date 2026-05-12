"""Alert message detection logic.

Classifies incoming Slack messages as Grafana/Prometheus alerts based on
the configurable rules defined in alert_detection.rules.

Rule types:
- ``bot_name``: Match the message's ``username`` field against a regex.
- ``text``: Match the message's ``text`` field against a regex.
- ``attachment_field``: Check whether an attachment field with the given
  title exists (value is not checked, only presence).
"""

from __future__ import annotations

import re

from owncall.config import AlertDetectionConfig, AlertRule


def is_alert_message(message: dict, cfg: AlertDetectionConfig) -> bool:
    """Return True if the message matches any configured alert rule."""
    if not cfg.enabled:
        return False

    for rule in cfg.rules:
        if _matches_rule(message, rule):
            return True
    return False


def _collect_searchable_text(message: dict) -> str:
    """Collect all text content from a message for pattern matching.

    Slack integrations may place alert content in the top-level text field,
    in attachments, or in Block Kit blocks. This function gathers text from
    all of these locations so that a single regex search covers them all.
    """
    parts: list[str] = []

    text = message.get("text", "")
    if text:
        parts.append(text)

    for attachment in message.get("attachments", []):
        for key in ("text", "fallback", "pretext", "title"):
            val = attachment.get(key, "")
            if val:
                parts.append(val)

    for block in message.get("blocks", []):
        block_text = block.get("text", {})
        if isinstance(block_text, dict) and block_text.get("text"):
            parts.append(block_text["text"])

    return "\n".join(parts)


def _matches_rule(message: dict, rule: AlertRule) -> bool:
    if rule.type == "bot_name":
        username = message.get("username", "")
        return bool(rule.pattern and re.search(rule.pattern, username))

    if rule.type == "text":
        text = _collect_searchable_text(message)
        return bool(rule.pattern and re.search(rule.pattern, text))

    if rule.type == "attachment_field":
        for attachment in message.get("attachments", []):
            for field in attachment.get("fields", []):
                if field.get("title") == rule.field:
                    return True
        return False

    return False


def extract_alert_summary(message: dict) -> str:
    """Build a human-readable summary of the alert message for the agent prompt."""
    parts: list[str] = []

    if message.get("username"):
        parts.append(f"Source: {message['username']}")

    text = message.get("text", "").strip()
    if text:
        parts.append(text)

    for attachment in message.get("attachments", []):
        if attachment.get("title"):
            parts.append(f"Title: {attachment['title']}")
        if attachment.get("text"):
            parts.append(attachment["text"])
        for field in attachment.get("fields", []):
            title = field.get("title", "")
            value = field.get("value", "")
            if title and value:
                parts.append(f"{title}: {value}")

    return "\n".join(parts) if parts else text
