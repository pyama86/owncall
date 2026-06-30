"""Tests for deterministic MCP tool response compression."""

import json
from types import SimpleNamespace

from owncall.mcp.compress import (
    apply_compression,
    minify_json,
    shrink_loki_response,
)


class TestMinifyJson:
    def test_strips_whitespace(self):
        text = json.dumps({"a": 1, "b": [1, 2, 3]}, indent=2)
        minified = minify_json(text)
        assert minified == '{"a":1,"b":[1,2,3]}'
        assert len(minified) < len(text)

    def test_passes_non_json_through(self):
        text = "not really json {oops"
        assert minify_json(text) == text

    def test_passes_empty_through(self):
        assert minify_json("") == ""

    def test_preserves_unicode(self):
        text = '{"msg": "こんにちは"}'
        assert "こんにちは" in minify_json(text)


class TestShrinkLokiResponse:
    def _loki_payload(
        self,
        stream_labels: dict | None = None,
        log_body: dict | None = None,
    ) -> str:
        return json.dumps(
            {
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": stream_labels or {"app": "foo", "namespace": "bar"},
                            "values": [
                                ["1700000000", json.dumps(log_body or {"message": "hi"})],
                            ],
                        }
                    ],
                },
            }
        )

    def test_minifies_when_no_drops_configured(self):
        text = self._loki_payload(stream_labels={"app": "foo", "noise": "yes"})
        shrunk = shrink_loki_response(text)
        assert "  " not in shrunk
        assert '"noise":"yes"' in shrunk

    def test_drops_stream_labels(self):
        text = self._loki_payload(stream_labels={"app": "foo", "cluster": "x", "job": "y"})
        shrunk = shrink_loki_response(text, drop_stream_labels=["cluster", "job"])
        assert "cluster" not in shrunk
        assert "job" not in shrunk
        assert "app" in shrunk  # untouched

    def test_drops_log_body_fields(self):
        text = self._loki_payload(
            log_body={"message": "hi", "service_name": "svc", "trace_id": "abc"}
        )
        shrunk = shrink_loki_response(text, drop_log_body_fields=["service_name"])
        assert "service_name" not in shrunk
        assert "trace_id" in shrunk
        assert "message" in shrunk

    def test_passes_unrelated_payload(self):
        text = '{"some": "other"}'
        # shape mismatch -> minify-only path
        shrunk = shrink_loki_response(
            text, drop_stream_labels=["cluster"], drop_log_body_fields=["service_name"]
        )
        assert shrunk == '{"some":"other"}'

    def test_passes_invalid_json(self):
        text = "{oops not json"
        assert shrink_loki_response(text) == text


class TestApplyCompression:
    def _result_with_text(self, text: str) -> SimpleNamespace:
        block = SimpleNamespace(type="text", text=text)
        return SimpleNamespace(content=[block])

    def test_replaces_smaller_text(self):
        original = json.dumps({"a": 1, "b": [1, 2, 3]}, indent=4)
        result = self._result_with_text(original)
        apply_compression(result, "some_tool")
        assert result.content[0].text == '{"a":1,"b":[1,2,3]}'

    def test_leaves_text_when_no_savings(self):
        original = '{"a":1}'
        result = self._result_with_text(original)
        apply_compression(result, "some_tool")
        assert result.content[0].text == original

    def test_uses_loki_path_for_loki_tools(self):
        loki_text = json.dumps(
            {
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": {"app": "x", "cluster": "y"},
                            "values": [["1", '{"m":"a"}']],
                        }
                    ],
                },
            },
            indent=2,
        )
        result = self._result_with_text(loki_text)
        apply_compression(
            result,
            "query_loki_logs",
            loki_tools=("query_loki_logs",),
            loki_drop_stream_labels=("cluster",),
        )
        assert "cluster" not in result.content[0].text

    def test_no_content_passthrough(self):
        result = SimpleNamespace(content=None)
        # Should not raise
        apply_compression(result, "any")
