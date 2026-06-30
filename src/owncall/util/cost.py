"""Format an agent run's token usage (and optional USD cost) as a Slack footer.

The openai-agents SDK exposes aggregated usage on ``result.context_wrapper.usage``
after ``Runner.run`` returns.  This module normalises that data and turns the
``RunResult`` into a one-line mrkdwn footer that handlers can append to the
response posted to Slack.

``UsageBreakdown`` is the single entry point shared by the Slack footer and the
Prometheus metrics module so token / cost fields are extracted from the SDK in
exactly one place.  When the SDK shape shifts only this file needs to follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from owncall.config import PricingConfig

if TYPE_CHECKING:  # avoid hard import: agents SDK version may shift the path
    from agents.run import RunResult

_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class UsageBreakdown:
    """Normalised view of one agent run's token usage and computed cost."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    requests: int
    cost_usd: float | None


def extract_usage(result: Any, pricing: PricingConfig) -> UsageBreakdown | None:
    """Return ``UsageBreakdown`` for a ``RunResult``, or ``None`` if unavailable.

    Returns ``None`` when the SDK did not produce usage (Judge-blocked turns,
    SDK shape mismatch, ``result`` itself is ``None``) so callers can branch
    uniformly on the result.
    """
    usage = _usage_from_result(result)
    if usage is None:
        return None

    cached = _cached_input_tokens(usage)
    return UsageBreakdown(
        input_tokens=int(usage.input_tokens),
        cached_input_tokens=cached,
        output_tokens=int(usage.output_tokens),
        total_tokens=int(usage.total_tokens),
        requests=int(usage.requests),
        cost_usd=_calc_usd(usage, pricing),
    )


def _cached_input_tokens(usage: Any) -> int:
    details = getattr(usage, "input_tokens_details", None)
    if details is None:
        return 0
    cached = getattr(details, "cached_tokens", None)
    if cached is None and isinstance(details, dict):
        cached = details.get("cached_tokens")
    return int(cached or 0)


def _calc_usd(usage: Any, pricing: PricingConfig) -> float | None:
    """Return the USD cost for this run, or None if pricing is not configured."""
    if pricing.input_per_1m is None and pricing.output_per_1m is None:
        return None

    cached = _cached_input_tokens(usage)
    uncached_input = max(0, usage.input_tokens - cached)

    cost = 0.0
    if pricing.input_per_1m is not None:
        cost += uncached_input * pricing.input_per_1m / _PER_MILLION
    # Fall back to the standard input rate when no cached rate is configured;
    # otherwise cached tokens would be silently free.
    cached_rate = pricing.cached_input_per_1m
    if cached_rate is None:
        cached_rate = pricing.input_per_1m
    if cached_rate is not None:
        cost += cached * cached_rate / _PER_MILLION
    if pricing.output_per_1m is not None:
        cost += usage.output_tokens * pricing.output_per_1m / _PER_MILLION
    return cost


def format_usage_footer(result: RunResult | None, pricing: PricingConfig) -> str:
    """Build a one-line Slack mrkdwn footer summarising token usage and cost.

    Returns an empty string when ``result`` (or its usage) is unavailable so
    callers can unconditionally pass the value as the ``footer`` argument.
    """
    breakdown = extract_usage(result, pricing)
    if breakdown is None:
        return ""

    parts = [f"{breakdown.total_tokens:,} tokens"]

    detail = f"in {breakdown.input_tokens:,}"
    if breakdown.cached_input_tokens:
        detail += f" (cached {breakdown.cached_input_tokens:,})"
    detail += f" / out {breakdown.output_tokens:,}"
    parts.append(detail)

    if breakdown.cost_usd is not None:
        parts.append(f"~${breakdown.cost_usd:.4f}")

    parts.append(f"{breakdown.requests} calls")

    return "\n_:money_with_wings: " + " · ".join(parts) + "_"


def _usage_from_result(result: Any) -> Any:
    if result is None:
        return None
    wrapper = getattr(result, "context_wrapper", None)
    if wrapper is None:
        return None
    return getattr(wrapper, "usage", None)
