"""Tests for config loading and environment variable expansion."""

import textwrap

import pytest

from owncall.config import _expand_env_vars, load_config


class TestEnvVarExpansion:
    def test_simple_var(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        assert _expand_env_vars("${MY_VAR}") == "hello"

    def test_var_with_default_present(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "set")
        assert _expand_env_vars("${MY_VAR:-default}") == "set"

    def test_var_with_default_absent(self, monkeypatch):
        monkeypatch.delenv("MY_VAR", raising=False)
        assert _expand_env_vars("${MY_VAR:-fallback}") == "fallback"

    def test_unset_no_default_left_as_is(self, monkeypatch):
        monkeypatch.delenv("UNSET_VAR", raising=False)
        assert _expand_env_vars("${UNSET_VAR}") == "${UNSET_VAR}"

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("A", "alpha")
        monkeypatch.setenv("B", "beta")
        assert _expand_env_vars("${A} and ${B}") == "alpha and beta"


class TestLoadConfig:
    def test_minimal_config(self, minimal_config_yaml):
        cfg = load_config(minimal_config_yaml)
        assert cfg.slack.app_token == "xapp-test"
        assert cfg.slack.bot_token == "xoxb-test"
        assert cfg.llm.model == "gpt-5.4-mini"
        assert cfg.agent.system_prompt == "You are a test assistant."
        assert len(cfg.mcp_servers) == 1
        assert cfg.mcp_servers[0].name == "grafana"
        assert cfg.mcp_servers[0].enabled is True

    def test_missing_app_token_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
        content = textwrap.dedent("""
            slack:
              bot_token: "xoxb-test"
        """)
        p = tmp_path / "bad.yml"
        p.write_text(content)
        with pytest.raises(ValueError, match="SLACK_APP_TOKEN"):
            load_config(str(p))

    def test_missing_bot_token_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        content = textwrap.dedent("""
            slack:
              app_token: "xapp-test"
        """)
        p = tmp_path / "bad.yml"
        p.write_text(content)
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            load_config(str(p))

    def test_env_var_overrides_config_token(self, minimal_config_yaml, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-from-env-override")
        cfg = load_config(minimal_config_yaml)
        assert cfg.slack.bot_token == "xoxb-from-env-override"

    def test_tokens_from_env_var_only(self, no_token_config_yaml, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-env-only")
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-env-only")
        cfg = load_config(no_token_config_yaml)
        assert cfg.slack.bot_token == "xoxb-env-only"
        assert cfg.slack.app_token == "xapp-env-only"

    def test_env_var_expansion_in_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_BOT_TOKEN", "xoxb-from-env")
        monkeypatch.setenv("TEST_APP_TOKEN", "xapp-from-env")
        content = textwrap.dedent("""
            slack:
              app_token: "${TEST_APP_TOKEN}"
              bot_token: "${TEST_BOT_TOKEN}"
        """)
        p = tmp_path / "env.yml"
        p.write_text(content)
        cfg = load_config(str(p))
        assert cfg.slack.bot_token == "xoxb-from-env"
        assert cfg.slack.app_token == "xapp-from-env"

    def test_disabled_mcp_server(self, tmp_path):
        content = textwrap.dedent("""
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            mcp_servers:
              - name: "github"
                type: "sse"
                url: "http://localhost:9000/sse"
                enabled: "false"
        """)
        p = tmp_path / "cfg.yml"
        p.write_text(content)
        cfg = load_config(str(p))
        assert cfg.mcp_servers[0].enabled is False

    def test_alert_rules_parsed(self, tmp_path):
        content = textwrap.dedent("""
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            alert_detection:
              enabled: true
              rules:
                - type: "bot_name"
                  pattern: "(?i)grafana"
                - type: "text"
                  pattern: "FIRING"
        """)
        p = tmp_path / "cfg.yml"
        p.write_text(content)
        cfg = load_config(str(p))
        assert len(cfg.alert_detection.rules) == 2
        assert cfg.alert_detection.rules[0].type == "bot_name"
        assert cfg.alert_detection.rules[1].type == "text"

    def test_default_values(self, minimal_config_yaml):
        cfg = load_config(minimal_config_yaml)
        assert cfg.llm.temperature is None
        assert cfg.response.max_length == 3000
        assert cfg.response.reaction_on_start == "eyes"
        assert cfg.response.reaction_on_complete == "white_check_mark"

    def test_channel_namespace_map_parsed(self, tmp_path):
        content = textwrap.dedent("""
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            channel_namespace_map:
              C01234567: "production"
              C09876543: "staging"
        """)
        p = tmp_path / "cfg.yml"
        p.write_text(content)
        cfg = load_config(str(p))
        assert cfg.channel_namespace_map == {"C01234567": "production", "C09876543": "staging"}

    def test_channel_namespace_map_defaults_empty(self, minimal_config_yaml):
        cfg = load_config(minimal_config_yaml)
        assert cfg.channel_namespace_map == {}

    def test_mention_channels_parsed(self, tmp_path):
        content = textwrap.dedent("""
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            mention:
              channels:
                - "C01234567"
                - "C09876543"
        """)
        p = tmp_path / "cfg.yml"
        p.write_text(content)
        cfg = load_config(str(p))
        assert cfg.mention.channels == ["C01234567", "C09876543"]

    def test_mention_channels_defaults_empty(self, minimal_config_yaml):
        cfg = load_config(minimal_config_yaml)
        assert cfg.mention.channels == []
