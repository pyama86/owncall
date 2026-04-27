"""Agent factory: combines system prompt, constraints, and MCP servers."""

from __future__ import annotations

from agents import Agent, ModelSettings

from owncall.config import AgentConfig, LLMConfig
from owncall.mcp.registry import AnyMCPServer


def build_system_prompt(cfg: AgentConfig) -> str:
    """Combine base system_prompt with the constraints list."""
    parts = [cfg.system_prompt.strip()] if cfg.system_prompt.strip() else []

    if cfg.constraints:
        rules = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(cfg.constraints))
        parts.append(f"## Constraints\n{rules}")

    return "\n\n".join(parts)


def create_agent(
    llm_cfg: LLMConfig,
    agent_cfg: AgentConfig,
    mcp_servers: list[AnyMCPServer],
) -> Agent:
    """Create an Agent bound to the given MCP servers."""
    instructions = build_system_prompt(agent_cfg)

    # Some models (e.g. gpt-5.4-mini) reject the temperature parameter entirely.
    # Only include it in ModelSettings when explicitly configured.
    model_settings = (
        ModelSettings(temperature=llm_cfg.temperature)
        if llm_cfg.temperature is not None
        else ModelSettings()
    )

    return Agent(
        name="OwnCall Assistant",
        instructions=instructions,
        mcp_servers=mcp_servers,
        model=llm_cfg.model,
        model_settings=model_settings,
    )
