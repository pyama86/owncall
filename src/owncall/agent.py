"""Agent factory: combines system prompt, constraints, and MCP servers.

When ``subagent.enabled`` is True the factory returns a two-tier setup: an
``investigator`` agent that actually holds the MCP servers and is invoked
through ``Agent.as_tool``, plus a ``primary`` agent without any MCP servers
that delegates every investigative call.  This keeps the bulky MCP responses
inside the (cheaper) investigator's context so they do not accumulate in the
primary's input history every turn.

When ``subagent.enabled`` is False the factory returns a bundle where
``primary`` and ``investigator`` are the same single agent that holds the
MCP servers directly — equivalent to the pre-subagent behaviour.

When ``judge.enabled`` is True the factory also attaches LLM-Judge input
and output guardrails to the primary agent.  The investigator is left
unguarded on purpose: in subagent mode the input judge runs before the
primary fires the ``investigate`` tool and the output judge runs against
the primary's final response, so both ends of the user-facing flow are
covered without paying for a Judge run on every internal tool call.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents import Agent, ModelSettings

from owncall.config import AgentConfig, JudgeConfig, LLMConfig, SubAgentConfig
from owncall.judge import build_guardrails
from owncall.mcp.registry import AnyMCPServer


@dataclass
class AgentBundle:
    """The pair of agents returned by :func:`create_agent`.

    ``primary`` is what handlers feed the user's input to.  ``investigator``
    is the agent that actually holds MCP servers — callers that need to talk
    directly to MCP (for example to fetch a list of namespaces) should use
    ``investigator`` so they do not waste the primary's turns.

    When sub-agent mode is disabled the two attributes point at the same
    object, so legacy call sites that always passed a single agent continue
    to work without branching.
    """

    primary: Agent
    investigator: Agent


def build_system_prompt(cfg: AgentConfig) -> str:
    """Combine base system_prompt with the constraints list."""
    parts = [cfg.system_prompt.strip()] if cfg.system_prompt.strip() else []

    if cfg.constraints:
        rules = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(cfg.constraints))
        parts.append(f"## Constraints\n{rules}")

    return "\n\n".join(parts)


def _model_settings(temperature: float | None) -> ModelSettings:
    """Build ModelSettings, omitting temperature when unset.

    Some models (e.g. gpt-5.4-mini) reject the temperature parameter entirely,
    so only include it when explicitly configured.
    """
    return ModelSettings(temperature=temperature) if temperature is not None else ModelSettings()


def _delegation_note(tool_name: str) -> str:
    """System-prompt addendum telling the primary to delegate via ``tool_name``."""
    return (
        "## Investigation policy\n"
        f"All investigative work (Grafana, Loki, Prometheus, code lookups, etc.) "
        f"must be delegated to the `{tool_name}` tool. You do not hold any MCP "
        f"tools yourself. Compose your final answer from `{tool_name}` responses; "
        "call it multiple times when you need to drill down."
    )


def create_agent(
    llm_cfg: LLMConfig,
    agent_cfg: AgentConfig,
    mcp_servers: list[AnyMCPServer],
    subagent_cfg: SubAgentConfig | None = None,
    judge_cfg: JudgeConfig | None = None,
) -> AgentBundle:
    """Create an :class:`AgentBundle` bound to the given MCP servers.

    When ``subagent_cfg.enabled`` is True a two-agent setup is returned with
    the MCP-holding investigator wrapped as a tool of the MCP-less primary.
    Otherwise a single-agent bundle is returned (``primary`` is also the
    ``investigator``).

    Judge guardrails (when ``judge_cfg.enabled`` is True) are attached to
    the primary only.  In subagent mode the investigator is left unguarded
    so internal tool invocations do not pay the Judge cost on every turn;
    user-facing input and output still flow through the primary and are
    therefore both audited.
    """
    base_instructions = build_system_prompt(agent_cfg)
    input_guardrails, output_guardrails = (
        build_guardrails(judge_cfg) if judge_cfg is not None else ([], [])
    )

    if subagent_cfg is not None and subagent_cfg.enabled:
        sub_model = subagent_cfg.model or llm_cfg.model
        investigator = Agent(
            name="OwnCall Investigator",
            instructions=subagent_cfg.system_prompt.strip() or base_instructions,
            mcp_servers=mcp_servers,
            model=sub_model,
            model_settings=_model_settings(llm_cfg.temperature),
        )
        # ``failure_error_function=None`` re-raises sub-agent failures (MCP
        # timeouts, MaxTurnsExceeded, etc.) up through ``Runner.run`` so the
        # handler can decide to surface a warning to Slack rather than letting
        # the primary LLM silently make up an answer.
        investigate_tool = investigator.as_tool(
            tool_name=subagent_cfg.tool_name,
            tool_description=subagent_cfg.tool_description,
            max_turns=subagent_cfg.max_turns,
            failure_error_function=None,
        )
        primary = Agent(
            name="OwnCall Assistant",
            instructions=f"{base_instructions}\n\n{_delegation_note(subagent_cfg.tool_name)}",
            tools=[investigate_tool],
            model=llm_cfg.model,
            model_settings=_model_settings(llm_cfg.temperature),
            input_guardrails=input_guardrails,
            output_guardrails=output_guardrails,
        )
        return AgentBundle(primary=primary, investigator=investigator)

    agent = Agent(
        name="OwnCall Assistant",
        instructions=base_instructions,
        mcp_servers=mcp_servers,
        model=llm_cfg.model,
        model_settings=_model_settings(llm_cfg.temperature),
        input_guardrails=input_guardrails,
        output_guardrails=output_guardrails,
    )
    return AgentBundle(primary=agent, investigator=agent)
