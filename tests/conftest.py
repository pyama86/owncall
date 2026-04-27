"""Shared test fixtures."""

import textwrap

import pytest


@pytest.fixture()
def minimal_config_yaml(tmp_path):
    """Return path to a minimal valid config YAML file (tokens in file)."""
    content = textwrap.dedent("""
        slack:
          app_token: "xapp-test"
          bot_token: "xoxb-test"
        llm:
          model: "gpt-5.4-mini"
        agent:
          system_prompt: "You are a test assistant."
        mcp_servers:
          - name: "grafana"
            type: "sse"
            url: "http://localhost:8000/sse"
            enabled: true
        alert_detection:
          enabled: true
          rules: []
        response:
          max_length: 3000
    """).strip()
    p = tmp_path / "config.yml"
    p.write_text(content)
    return str(p)


@pytest.fixture()
def no_token_config_yaml(tmp_path):
    """Return path to a config YAML file with no slack tokens (env var only)."""
    content = textwrap.dedent("""
        slack: {}
        mcp_servers: []
    """).strip()
    p = tmp_path / "config.yml"
    p.write_text(content)
    return str(p)
