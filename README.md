# OwnCall

MCP-powered Slack bot for interactive Grafana/Prometheus alert investigation.

OwnCall connects to Grafana MCP (and optionally GitHub MCP) and gives your team an on-call assistant directly in Slack.

## Features

- **@mention investigation** — mention the bot in any channel or thread to ask questions about your Grafana dashboards, Loki logs, or Prometheus metrics interactively.
- **Alert auto-investigation** — when Grafana Alerting or Alertmanager posts a firing alert to Slack, the bot automatically investigates it and replies in the thread.
- **YAML-driven prompts** — customise the system prompt and add constraints (e.g. "only search the last 3 hours") in `config.yml` without touching code.
- **Multi-MCP support** — Grafana MCP is built-in; GitHub MCP can be enabled via a single environment variable to include source code context in investigations.
- **Socket Mode** — no public endpoint required; runs entirely behind your firewall.

## Requirements

- Python 3.10+
- OpenAI API key
- Grafana MCP server (Docker image: `grafana/mcp-grafana`)
- Slack app with Socket Mode enabled (see [Slack App Setup](#slack-app-setup))

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Configure

Copy the example config and fill in your credentials:

```bash
cp config.example.yml config.yml
```

Edit `config.yml`:

```yaml
slack:
  bot_token: "xoxb-..."
  app_token: "xapp-..."

llm:
  model: "gpt-5.4-mini"

agent:
  system_prompt: |
    You are an SRE assistant. Use MCP tools to investigate Grafana alerts.
  constraints:
    - "Search only the last 3 hours unless a time range is specified."

mcp_servers:
  - name: "grafana"
    type: "sse"
    url: "http://localhost:8000/sse"
    enabled: true
```

### 3. Start the Grafana MCP server

```bash
docker run -p 8000:8000 \
  -e GRAFANA_URL=https://your-grafana.example.com \
  -e GRAFANA_SERVICE_ACCOUNT_TOKEN=your-token \
  grafana/mcp-grafana -t sse
```

### 4. Start the bot

```bash
export OPENAI_API_KEY=sk-...
owncall -c config.yml
```

### Docker Compose (all-in-one)

```bash
cp config.example.yml config.yml  # fill in agent and alert_detection sections
export OPENAI_API_KEY=sk-...
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export GRAFANA_URL=https://your-grafana.example.com
export GRAFANA_SERVICE_ACCOUNT_TOKEN=your-token
docker compose up
```

## Slack App Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. **Socket Mode** tab → Enable Socket Mode → generate an **App-Level Token** with `connections:write` scope (`xapp-...`).
3. **OAuth & Permissions** → add Bot Token Scopes:
   - `app_mentions:read`
   - `channels:history`
   - `chat:write`
   - `files:write`
   - `reactions:write`
   - `groups:history` (for private channels)
4. **Event Subscriptions** → Enable Events → **Subscribe to bot events**:
   - `app_mention`
   - `message.channels`
   - `message.groups`
5. Install the app to your workspace and copy the **Bot User OAuth Token** (`xoxb-...`).

## GitHub MCP (optional)

To enable source code lookup during investigations, run a GitHub MCP server
and set the following in your environment or `config.yml`:

```bash
export GITHUB_MCP_ENABLED=true
export GITHUB_MCP_URL=http://localhost:9000/sse
```

Then start a GitHub MCP server (see the `docker-compose.yml` for an example).

## Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `slack.bot_token` | — | Slack Bot Token (`xoxb-...`) |
| `slack.app_token` | — | Slack App-Level Token (`xapp-...`) |
| `llm.model` | `gpt-5.4-mini` | OpenAI model name |
| `llm.temperature` | `0.2` | Sampling temperature |
| `agent.system_prompt` | — | Base system prompt for the agent |
| `agent.constraints` | `[]` | Additional rules appended to the system prompt |
| `mcp_servers[].name` | — | Human-readable server name |
| `mcp_servers[].type` | `sse` | Transport: `sse`, `streamable_http`, `stdio` |
| `mcp_servers[].url` | — | SSE endpoint URL |
| `mcp_servers[].enabled` | `true` | Set to `false` or `${ENV_VAR:-false}` to disable |
| `alert_detection.enabled` | `true` | Toggle alert auto-investigation |
| `alert_detection.channels` | `[]` | Restrict to specific channel IDs (empty = all) |
| `alert_detection.rules` | — | List of detection rules (see `config.example.yml`) |
| `response.max_length` | `3000` | Max characters per message; longer responses are uploaded as files |
| `response.reaction_on_start` | `eyes` | Reaction added while processing |
| `response.reaction_on_complete` | `white_check_mark` | Reaction added on completion |


## License

MIT
