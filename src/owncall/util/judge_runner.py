"""``Runner.run`` wrapper that turns Judge tripwires into a blocked response.

Each Slack handler invokes the agent through this helper so the
guardrail-trip handling is centralised.  When the Judge fires the helper
returns a :class:`JudgedRunResult` with ``blocked=True`` and the configured
``blocked_message`` instead of letting
``InputGuardrailTripwireTriggered`` / ``OutputGuardrailTripwireTriggered``
propagate to the handler.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from agents import (
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    Runner,
)

from owncall.config import JudgeConfig

logger = logging.getLogger(__name__)


def _describe_input(input_data: Any) -> str:
    if isinstance(input_data, str):
        return f"str(len={len(input_data)})"
    if isinstance(input_data, list):
        return f"list(items={len(input_data)})"
    return type(input_data).__name__


@dataclass
class JudgedRunResult:
    """Combined return type capturing both the run and the Judge verdict."""

    final_output: str
    raw_result: Any  # ``agents.run.RunResult`` or ``None`` when blocked
    blocked: bool = False
    block_stage: str = ""  # "input" | "output" | ""


async def run_agent_with_judge(
    agent: Any,
    input_data: Any,
    *,
    max_turns: int,
    judge_cfg: JudgeConfig,
) -> JudgedRunResult:
    """Run the agent and translate Judge tripwires into a blocked response.

    The original input is passed as the run ``context`` so the output Judge
    can compare the response against the source thread (see
    :func:`owncall.judge.build_output_guardrail`).
    """
    started = time.monotonic()
    logger.info(
        "Runner.run start: max_turns=%d input=%s judge_enabled=%s",
        max_turns,
        _describe_input(input_data),
        judge_cfg.enabled,
    )
    try:
        result = await Runner.run(agent, input_data, max_turns=max_turns, context=input_data)
    except InputGuardrailTripwireTriggered as exc:
        elapsed_ms = (time.monotonic() - started) * 1000
        info = _extract_verdict(exc)
        logger.warning(
            "Runner.run blocked by input judge: severity=%s categories=%s"
            " elapsed_ms=%.0f reason=%s",
            info.get("severity", ""),
            info.get("categories", []),
            elapsed_ms,
            info.get("reasoning", ""),
        )
        return JudgedRunResult(
            final_output=judge_cfg.blocked_message,
            raw_result=None,
            blocked=True,
            block_stage="input",
        )
    except OutputGuardrailTripwireTriggered as exc:
        elapsed_ms = (time.monotonic() - started) * 1000
        info = _extract_verdict(exc)
        logger.warning(
            "Runner.run blocked by output judge: severity=%s categories=%s"
            " elapsed_ms=%.0f reason=%s",
            info.get("severity", ""),
            info.get("categories", []),
            elapsed_ms,
            info.get("reasoning", ""),
        )
        return JudgedRunResult(
            final_output=judge_cfg.blocked_message,
            raw_result=None,
            blocked=True,
            block_stage="output",
        )

    elapsed_ms = (time.monotonic() - started) * 1000
    final_output = result.final_output
    final_length = len(final_output) if isinstance(final_output, str) else -1
    logger.info(
        "Runner.run finished: blocked=False elapsed_ms=%.0f final_output_length=%d",
        elapsed_ms,
        final_length,
    )
    return JudgedRunResult(
        final_output=final_output,
        raw_result=result,
        blocked=False,
    )


def _extract_verdict(exc: Exception) -> dict:
    """Pull the JudgeVerdict dict out of a guardrail exception, if present."""
    guardrail_result = getattr(exc, "guardrail_result", None)
    if guardrail_result is None:
        return {}
    output = getattr(guardrail_result, "output", None)
    info = getattr(output, "output_info", None) if output is not None else None
    return info if isinstance(info, dict) else {}
