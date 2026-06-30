"""Tests for cost extraction and footer formatting."""

from types import SimpleNamespace

from owncall.config import PricingConfig
from owncall.util.cost import extract_usage, format_usage_footer


def _make_result(
    *,
    input_tokens: int,
    output_tokens: int,
    requests: int = 1,
    cached: int = 0,
) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        requests=requests,
        input_tokens_details=SimpleNamespace(cached_tokens=cached),
    )
    return SimpleNamespace(context_wrapper=SimpleNamespace(usage=usage))


class TestExtractUsage:
    def test_returns_none_for_missing_result(self):
        assert extract_usage(None, PricingConfig()) is None

    def test_returns_none_when_usage_absent(self):
        result = SimpleNamespace(context_wrapper=SimpleNamespace(usage=None))
        assert extract_usage(result, PricingConfig()) is None

    def test_extracts_token_counts(self):
        result = _make_result(input_tokens=1000, output_tokens=500, cached=200)
        breakdown = extract_usage(result, PricingConfig())
        assert breakdown is not None
        assert breakdown.input_tokens == 1000
        assert breakdown.cached_input_tokens == 200
        assert breakdown.output_tokens == 500
        assert breakdown.total_tokens == 1500
        assert breakdown.cost_usd is None  # pricing not configured

    def test_returns_none_when_pricing_unset(self):
        result = _make_result(input_tokens=1000, output_tokens=500)
        breakdown = extract_usage(result, PricingConfig())
        assert breakdown is not None
        assert breakdown.cost_usd is None

    def test_cost_combines_input_and_output(self):
        pricing = PricingConfig(input_per_1m=2.5, output_per_1m=15.0)
        result = _make_result(input_tokens=1_000_000, output_tokens=100_000)
        breakdown = extract_usage(result, pricing)
        assert breakdown is not None
        # 1M input @ $2.5 + 100k output @ $15/M = 2.5 + 1.5 = 4.0
        assert breakdown.cost_usd == 4.0

    def test_cached_rate_falls_back_to_input_rate(self):
        pricing = PricingConfig(input_per_1m=2.0, output_per_1m=0.0)
        result = _make_result(input_tokens=1_000_000, output_tokens=0, cached=500_000)
        breakdown = extract_usage(result, pricing)
        # uncached=500k @ $2 + cached=500k @ $2 (fallback) = $2.0
        assert breakdown is not None
        assert breakdown.cost_usd == 2.0

    def test_cached_rate_overrides_when_set(self):
        pricing = PricingConfig(input_per_1m=2.0, output_per_1m=0.0, cached_input_per_1m=0.5)
        result = _make_result(input_tokens=1_000_000, output_tokens=0, cached=500_000)
        breakdown = extract_usage(result, pricing)
        # uncached=500k @ $2 + cached=500k @ $0.5 = $1.0 + $0.25 = $1.25
        assert breakdown is not None
        assert breakdown.cost_usd == 1.25


class TestFormatUsageFooter:
    def test_empty_when_no_result(self):
        assert format_usage_footer(None, PricingConfig()) == ""

    def test_format_without_cost(self):
        result = _make_result(input_tokens=1000, output_tokens=500, cached=200, requests=3)
        footer = format_usage_footer(result, PricingConfig())
        assert ":money_with_wings:" in footer
        assert "1,500 tokens" in footer
        assert "in 1,000" in footer
        assert "(cached 200)" in footer
        assert "out 500" in footer
        assert "3 calls" in footer

    def test_format_with_cost(self):
        result = _make_result(input_tokens=1_000_000, output_tokens=100_000)
        pricing = PricingConfig(input_per_1m=2.5, output_per_1m=15.0)
        footer = format_usage_footer(result, pricing)
        assert "~$4.0000" in footer
