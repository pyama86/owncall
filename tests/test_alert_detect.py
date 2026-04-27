"""Tests for alert detection logic."""

from owncall.config import AlertDetectionConfig, AlertRule
from owncall.util.alert_detect import extract_alert_summary, is_alert_message


def _make_cfg(rules, enabled=True, channels=None):
    return AlertDetectionConfig(
        enabled=enabled,
        channels=channels or [],
        rules=rules,
    )


class TestIsAlertMessage:
    def test_disabled_config_always_false(self):
        cfg = _make_cfg(
            rules=[AlertRule(type="text", pattern="FIRING")],
            enabled=False,
        )
        msg = {"text": "[FIRING:1] High error rate", "bot_id": "B123"}
        assert is_alert_message(msg, cfg) is False

    def test_bot_name_match(self):
        cfg = _make_cfg([AlertRule(type="bot_name", pattern="(?i)grafana")])
        msg = {"username": "Grafana Alerts", "text": "something"}
        assert is_alert_message(msg, cfg) is True

    def test_bot_name_no_match(self):
        cfg = _make_cfg([AlertRule(type="bot_name", pattern="(?i)grafana")])
        msg = {"username": "Jenkins", "text": "Build failed"}
        assert is_alert_message(msg, cfg) is False

    def test_text_match(self):
        cfg = _make_cfg([AlertRule(type="text", pattern=r"\[FIRING:\d+\]")])
        msg = {"text": "[FIRING:3] High CPU usage"}
        assert is_alert_message(msg, cfg) is True

    def test_text_no_match(self):
        cfg = _make_cfg([AlertRule(type="text", pattern=r"\[FIRING:\d+\]")])
        msg = {"text": "Everything looks fine"}
        assert is_alert_message(msg, cfg) is False

    def test_attachment_field_match(self):
        cfg = _make_cfg([AlertRule(type="attachment_field", field="alertname")])
        msg = {
            "text": "",
            "attachments": [{"fields": [{"title": "alertname", "value": "HighErrorRate"}]}],
        }
        assert is_alert_message(msg, cfg) is True

    def test_attachment_field_no_match(self):
        cfg = _make_cfg([AlertRule(type="attachment_field", field="alertname")])
        msg = {
            "text": "",
            "attachments": [{"fields": [{"title": "severity", "value": "critical"}]}],
        }
        assert is_alert_message(msg, cfg) is False

    def test_first_matching_rule_wins(self):
        cfg = _make_cfg(
            [
                AlertRule(type="bot_name", pattern="(?i)grafana"),
                AlertRule(type="text", pattern="FIRING"),
            ]
        )
        # Only bot_name matches, text does not
        msg = {"username": "Grafana", "text": "All good"}
        assert is_alert_message(msg, cfg) is True

    def test_no_rules_returns_false(self):
        cfg = _make_cfg([])
        msg = {"text": "[FIRING:1] Alert", "username": "Grafana"}
        assert is_alert_message(msg, cfg) is False

    def test_unknown_rule_type_skipped(self):
        cfg = _make_cfg([AlertRule(type="unknown_type", pattern=".*")])
        msg = {"text": "anything"}
        assert is_alert_message(msg, cfg) is False


class TestExtractAlertSummary:
    def test_plain_text_message(self):
        msg = {"text": "Alert fired", "username": "alertmanager"}
        summary = extract_alert_summary(msg)
        assert "Alert fired" in summary
        assert "alertmanager" in summary

    def test_attachment_fields_included(self):
        msg = {
            "text": "[FIRING:1]",
            "attachments": [
                {
                    "title": "High Error Rate",
                    "fields": [
                        {"title": "alertname", "value": "HighErrorRate"},
                        {"title": "severity", "value": "critical"},
                    ],
                }
            ],
        }
        summary = extract_alert_summary(msg)
        assert "HighErrorRate" in summary
        assert "critical" in summary
        assert "High Error Rate" in summary

    def test_empty_message(self):
        msg = {}
        summary = extract_alert_summary(msg)
        assert summary == ""
