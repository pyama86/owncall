"""Tests for the newly added config sections (pricing, metrics, etc.)."""

import textwrap

import pytest

from owncall.config import load_config


def _write(tmp_path, body: str) -> str:
    content = textwrap.dedent(body).strip()
    p = tmp_path / "cfg.yml"
    p.write_text(content)
    return str(p)


class TestPricing:
    def test_defaults_to_none(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            """,
        )
        cfg = load_config(path)
        assert cfg.llm.pricing.input_per_1m is None
        assert cfg.llm.pricing.output_per_1m is None
        assert cfg.llm.pricing.cached_input_per_1m is None

    def test_parses_pricing(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            llm:
              model: "gpt-5.4"
              pricing:
                input_per_1m: 2.5
                output_per_1m: 15.0
                cached_input_per_1m: 0.25
            """,
        )
        cfg = load_config(path)
        assert cfg.llm.pricing.input_per_1m == 2.5
        assert cfg.llm.pricing.output_per_1m == 15.0
        assert cfg.llm.pricing.cached_input_per_1m == 0.25


class TestAgentTimeout:
    def test_default_run_timeout(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            """,
        )
        cfg = load_config(path)
        assert cfg.agent.run_timeout_seconds == 300.0

    def test_custom_run_timeout(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            agent:
              run_timeout_seconds: 120
            """,
        )
        cfg = load_config(path)
        assert cfg.agent.run_timeout_seconds == 120.0


class TestMCPServerExtras:
    def test_default_filter_and_timeouts(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            mcp_servers:
              - name: "grafana"
                type: "sse"
                url: "http://localhost:8000/sse"
                enabled: true
            """,
        )
        cfg = load_config(path)
        srv = cfg.mcp_servers[0]
        assert srv.allowed_tools == []
        assert srv.blocked_tools == []
        assert srv.timeout == 30.0
        assert srv.sse_read_timeout == 300.0
        assert srv.client_session_timeout_seconds == 60.0
        assert srv.max_retry_attempts == 2
        assert srv.retry_backoff_seconds_base == 1.0

    def test_custom_filter_and_timeouts(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            mcp_servers:
              - name: "grafana"
                type: "sse"
                url: "http://localhost:8000/sse"
                enabled: true
                allowed_tools: ["query_loki_logs", "query_prometheus"]
                blocked_tools: ["create_alert_rule"]
                timeout: 10
                sse_read_timeout: 60
                client_session_timeout_seconds: 20
                max_retry_attempts: 5
                retry_backoff_seconds_base: 0.5
            """,
        )
        cfg = load_config(path)
        srv = cfg.mcp_servers[0]
        assert srv.allowed_tools == ["query_loki_logs", "query_prometheus"]
        assert srv.blocked_tools == ["create_alert_rule"]
        assert srv.timeout == 10.0
        assert srv.sse_read_timeout == 60.0
        assert srv.max_retry_attempts == 5


class TestSubAgent:
    def test_default_disabled(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            """,
        )
        cfg = load_config(path)
        assert cfg.subagent.enabled is False
        assert cfg.subagent.tool_name == "investigate"

    def test_enabled_with_overrides(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            subagent:
              enabled: true
              model: "gpt-5.4-mini"
              tool_name: "research"
              max_turns: 15
            """,
        )
        cfg = load_config(path)
        assert cfg.subagent.enabled is True
        assert cfg.subagent.model == "gpt-5.4-mini"
        assert cfg.subagent.tool_name == "research"
        assert cfg.subagent.max_turns == 15


class TestToolCompression:
    def test_default_disabled(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            """,
        )
        cfg = load_config(path)
        assert cfg.tool_compression.enabled is False
        assert cfg.tool_compression.summarize_threshold_chars == 30_000

    def test_validation_rejects_negative_threshold(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            tool_compression:
              summarize_threshold_chars: -1
            """,
        )
        with pytest.raises(ValueError, match="summarize_threshold_chars"):
            load_config(path)

    def test_validation_rejects_bad_ratio(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            tool_compression:
              min_reduction_ratio: 1.5
            """,
        )
        with pytest.raises(ValueError, match="min_reduction_ratio"):
            load_config(path)

    def test_loki_lists(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            tool_compression:
              enabled: true
              loki_tools: ["query_loki_logs", "grafana_query_loki_logs"]
              loki_drop_stream_labels: ["cluster", "job"]
              loki_drop_log_body_fields: ["service_name"]
            """,
        )
        cfg = load_config(path)
        assert cfg.tool_compression.loki_tools == [
            "query_loki_logs",
            "grafana_query_loki_logs",
        ]
        assert cfg.tool_compression.loki_drop_stream_labels == ["cluster", "job"]
        assert cfg.tool_compression.loki_drop_log_body_fields == ["service_name"]


class TestJudge:
    def test_default_disabled(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            """,
        )
        cfg = load_config(path)
        assert cfg.judge.enabled is False
        # Stages default to enabled so flipping judge.enabled=true is enough
        assert cfg.judge.input.enabled is True
        assert cfg.judge.output.enabled is True
        # Default prompts ship in code, not in the file
        assert cfg.judge.input.system_prompt == ""
        assert cfg.judge.output.system_prompt == ""
        # Resolver falls back to the built-in defaults
        assert "internal Slack bot" in cfg.judge.input_prompt()
        assert "secret_leak" in cfg.judge.output_prompt()

    def test_custom_prompts_via_file(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            judge:
              enabled: true
              model: "gpt-cheap"
              temperature: 0.0
              fail_open: true
              blocked_message: ":no_entry: nope"
              input:
                enabled: true
                system_prompt: "CUSTOM INPUT JUDGE"
              output:
                enabled: false
                system_prompt: "CUSTOM OUTPUT JUDGE"
            """,
        )
        cfg = load_config(path)
        assert cfg.judge.enabled is True
        assert cfg.judge.model == "gpt-cheap"
        assert cfg.judge.temperature == 0.0
        assert cfg.judge.fail_open is True
        assert cfg.judge.blocked_message == ":no_entry: nope"
        assert cfg.judge.input.enabled is True
        assert cfg.judge.input_prompt() == "CUSTOM INPUT JUDGE"
        assert cfg.judge.output.enabled is False
        assert cfg.judge.output_prompt() == "CUSTOM OUTPUT JUDGE"

    def test_temperature_none_passes_through(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            judge:
              enabled: true
              temperature: null
            """,
        )
        cfg = load_config(path)
        assert cfg.judge.temperature is None


class TestCostFooterFlag:
    def test_default_off(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            """,
        )
        cfg = load_config(path)
        assert cfg.response.cost_footer is False

    def test_enabled(self, tmp_path):
        path = _write(
            tmp_path,
            """
            slack:
              app_token: "xapp-test"
              bot_token: "xoxb-test"
            response:
              cost_footer: true
            """,
        )
        cfg = load_config(path)
        assert cfg.response.cost_footer is True
