"""Configuration loading and validation from YAML files.

Secret values (Slack tokens, MCP URLs) are resolved with the following priority:

  1. Environment variable (e.g. SLACK_BOT_TOKEN)
  2. Config file value (which may itself contain ${VAR} placeholders)

This means secrets can be kept entirely out of the config file and injected
via the process environment, which is the recommended approach for production
deployments (Docker, Kubernetes, etc.).

Supported environment variables
--------------------------------
SLACK_BOT_TOKEN   – Slack Bot Token (xoxb-...)
SLACK_APP_TOKEN   – Slack App-Level Token for Socket Mode (xapp-...)
OPENAI_API_KEY    – Read directly by the openai-agents SDK; not needed in config
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

# Mapping from well-known environment variable names to their config path.
# Values from these env vars always override the config file.
_ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    # env var name -> (section, key)
    "SLACK_BOT_TOKEN": ("slack", "bot_token"),
    "SLACK_APP_TOKEN": ("slack", "app_token"),
}


def _expand_env_vars(text: str) -> str:
    """Expand ${VAR} and ${VAR:-default} placeholders using environment variables."""

    def _replace(match: re.Match) -> str:
        var = match.group(1)
        default = match.group(2)  # None when no :- present
        value = os.environ.get(var)
        if value is not None:
            return value
        if default is not None:
            return default
        return match.group(0)  # leave unexpanded when no default and not set

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}", _replace, text)


def _apply_env_overrides(data: dict) -> None:
    """Apply well-known environment variables on top of the parsed YAML data.

    Environment variables take priority over config file values so that secrets
    can be injected without touching the config file.
    """
    for env_var, (section, key) in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value:
            if not isinstance(data.get(section), dict):
                data[section] = {}
            data[section][key] = value


@dataclass
class SlackConfig:
    app_token: str
    bot_token: str


@dataclass
class LLMConfig:
    model: str = "gpt-5.4-mini"
    temperature: float | None = None


@dataclass
class AgentConfig:
    system_prompt: str = ""
    constraints: list[str] = field(default_factory=list)


@dataclass
class MCPServerConfig:
    name: str
    type: str  # "sse" | "streamable_http" | "stdio"
    url: str = ""
    command: list[str] = field(default_factory=list)
    enabled: bool = True
    cache_tools: bool = True
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class AlertRule:
    type: str  # "bot_name" | "text" | "attachment_field"
    pattern: str = ""
    field: str = ""


@dataclass
class AlertDetectionConfig:
    enabled: bool = True
    channels: list[str] = field(default_factory=list)
    rules: list[AlertRule] = field(default_factory=list)


@dataclass
class MentionConfig:
    channels: list[str] = field(default_factory=list)


@dataclass
class ResponseConfig:
    max_length: int = 3000
    thread_reply: bool = True
    reaction_on_start: str = "eyes"
    reaction_on_complete: str = "white_check_mark"


@dataclass
class AppConfig:
    slack: SlackConfig
    llm: LLMConfig
    agent: AgentConfig
    mcp_servers: list[MCPServerConfig]
    alert_detection: AlertDetectionConfig
    response: ResponseConfig
    mention: MentionConfig = field(default_factory=MentionConfig)
    channel_namespace_map: dict[str, str] = field(default_factory=dict)


def _parse_bool(value: Any) -> bool:
    """Convert string/bool values to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _parse_mcp_server(raw: dict) -> MCPServerConfig:
    return MCPServerConfig(
        name=raw["name"],
        type=raw.get("type", "sse"),
        url=raw.get("url", ""),
        command=raw.get("command", []),
        enabled=_parse_bool(raw.get("enabled", True)),
        cache_tools=_parse_bool(raw.get("cache_tools", True)),
        headers=raw.get("headers", {}),
    )


def _parse_alert_rule(raw: dict) -> AlertRule:
    return AlertRule(
        type=raw["type"],
        pattern=raw.get("pattern", ""),
        field=raw.get("field", ""),
    )


def load_config(path: str) -> AppConfig:
    """Load and validate configuration from a YAML file.

    Resolution order for secret fields:
      1. Environment variable (SLACK_BOT_TOKEN, SLACK_APP_TOKEN)
      2. Config file value (literal or ${VAR} placeholder)
    """
    with open(path) as f:
        raw_text = f.read()

    expanded = _expand_env_vars(raw_text)
    data: dict = yaml.safe_load(expanded) or {}

    # Environment variables override config file values for secrets
    _apply_env_overrides(data)

    slack_data = data.get("slack", {})
    if not slack_data.get("bot_token"):
        raise ValueError(
            "Slack bot token is required. "
            "Set SLACK_BOT_TOKEN environment variable or slack.bot_token in config."
        )
    if not slack_data.get("app_token"):
        raise ValueError(
            "Slack app token is required. "
            "Set SLACK_APP_TOKEN environment variable or slack.app_token in config."
        )

    llm_data = data.get("llm", {})
    agent_data = data.get("agent", {})
    alert_data = data.get("alert_detection", {})
    mention_data = data.get("mention", {})
    response_data = data.get("response", {})

    return AppConfig(
        slack=SlackConfig(
            app_token=slack_data["app_token"],
            bot_token=slack_data["bot_token"],
        ),
        llm=LLMConfig(
            model=llm_data.get("model", "gpt-5.4-mini"),
            temperature=float(llm_data["temperature"]) if "temperature" in llm_data else None,
        ),
        agent=AgentConfig(
            system_prompt=agent_data.get("system_prompt", ""),
            constraints=agent_data.get("constraints", []),
        ),
        mcp_servers=[_parse_mcp_server(s) for s in data.get("mcp_servers", [])],
        alert_detection=AlertDetectionConfig(
            enabled=_parse_bool(alert_data.get("enabled", True)),
            channels=alert_data.get("channels", []),
            rules=[_parse_alert_rule(r) for r in alert_data.get("rules", [])],
        ),
        response=ResponseConfig(
            max_length=int(response_data.get("max_length", 3000)),
            thread_reply=_parse_bool(response_data.get("thread_reply", True)),
            reaction_on_start=response_data.get("reaction_on_start", "eyes"),
            reaction_on_complete=response_data.get("reaction_on_complete", "white_check_mark"),
        ),
        mention=MentionConfig(
            channels=mention_data.get("channels", []),
        ),
        channel_namespace_map=data.get("channel_namespace_map", {}),
    )
