# Agent Control Plane

**AI Agent Operations Platform** — discover, inventory, monitor, and track costs for AI agents across your organization.

[![Tests](https://github.com/iknowkungfubar/agent-control-plane/actions/workflows/ci.yml/badge.svg)](https://github.com/iknowkungfubar/agent-control-plane/actions)
[![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)](https://github.com/iknowkungfubar/agent-control-plane)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The Problem

Organizations are deploying AI agents faster than they can manage them:
- **57%** of organizations have AI agents in production (2026)
- **49%** of enterprises run 10+ agents
- **92%** of CISOs lack full visibility into AI agents in their organization
- Companies report **"AI agent sprawl"** — duplicate agents, unknown costs, unchecked security risks

Existing tools (Langfuse, LangSmith, Arize) focus on **LLM tracing for developers**. There's no **IT ops governance layer** — no single pane that discovers what agents exist, who deployed them, what they cost, and whether they're healthy.

**Agent Control Plane fills that gap.**

## Features

- **Agent Discovery** — Scan configured endpoints and register agents in inventory
- **Health Monitoring** — Ping agent endpoints, detect failures and degradation
- **Cost Tracking** — Estimate monthly spend per agent/provider
- **Inventory Management** — Full CRUD for agent records with status history
- **Export** — CSV and JSON export for compliance reporting
- **CLI Interface** — All operations available from the terminal

## Installation

```bash
# Clone the repository
git clone https://github.com/iknowkungfubar/agent-control-plane.git
cd agent-control-plane

# Install with uv (recommended)
uv sync --group dev

# Or with pip
pip install -e .
```

## Quick Start

### 1. Configure your agents

Create a `config.yaml` file:

```yaml
agents:
  - name: my-claude-agent
    url: http://localhost:8080
    provider: anthropic
    tags: [production, llm]

  - name: my-openai-agent
    url: http://localhost:8081
    provider: openai
    health_check_path: /healthz
    tags: [staging]

  - name: local-llm
    url: http://localhost:1234/v1
    provider: lm-studio
    tags: [local, dev]
```

Set `ACP_CONFIG` to point at it, or put it in `~/.acp/config.yaml`.

### 2. Scan & Discover

```bash
acp scan
# ✓ Scan complete. 3 agent(s) in inventory.
```

### 3. Check Health

```bash
acp health
# ┌───────────────────── Health Check Results ─────────────────────┐
# │ Agent           │ Status   │ Response │ Details               │
# ├─────────────────┼──────────┼──────────┼───────────────────────┤
# │ my-claude-agent │ online   │    45ms  │ OK                    │
# │ my-openai-agent │ online   │    32ms  │ OK                    │
# │ local-llm       │ offline  │        - │ connection refused    │
# └─────────────────┴──────────┴──────────┴───────────────────────┘
# 2/3 agents online
```

### 4. List Inventory

```bash
acp list
```

### 5. Track Costs

```bash
acp cost
# ┌───────────────── Cost Estimates ─────────────────┐
# │ Agent           │ Tokens In  │ Tokens Out │ Cost  │
# ├─────────────────┼────────────┼────────────┼───────┤
# │ my-claude-agent │  1,000,000 │    200,000 │ $4.50 │
# └─────────────────┴────────────┴────────────┴───────┘
# Total estimated monthly cost: $4.50
```

### 6. Export for Compliance

```bash
acp export --format json --output report.json
acp export --format csv --output report.csv
```

### 7. Fleet Status

```bash
acp status
# ╔══════════════════════════════════════════╗
# ║          Agent Fleet Status              ║
# ╠══════════════════════════════════════════╣
# ║ Total Agents: 3                         ║
# ║   Online:  2                            ║
# ║   Offline: 1                            ║
# ║   Degraded: 0                           ║
# ║   Unknown: 0                            ║
# ║                                          ║
# ║ Total Checks Run: 12                    ║
# ║ Est. Monthly Cost: $4.50                 ║
# ╚══════════════════════════════════════════╝
```

## Configuration

The Agent Control Plane uses environment variables for configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `ACP_CONFIG` | `~/.acp/config.yaml` | Path to agent configuration YAML |
| `ACP_HOME` | `~/.acp` | Data directory (database, exports) |

### Agent Configuration Format

```yaml
agents:
  - name: string              # Required: unique agent name
    url: string               # Required: base URL of the agent endpoint
    provider: string           # Optional: openai, anthropic, google, mistral,
                               #   ollama, lm-studio, opencode, custom (default: custom)
    health_check_path: string  # Optional: health endpoint path (default: /health)
    tags: [string]             # Optional: list of tags for filtering
    metadata: {key: value}     # Optional: extra metadata
```

### Provider Cost Rates

| Provider | Input (per 1K tokens) | Output (per 1K tokens) |
|----------|----------------------|-----------------------|
| OpenAI | $0.0025 | $0.010 |
| Anthropic | $0.0030 | $0.015 |
| Google | $0.0015 | $0.005 |
| Mistral | $0.0020 | $0.008 |
| OpenCode | $0.0010 | $0.004 |
| Ollama (local) | Free | Free |
| LM Studio (local) | Free | Free |

## Commands

| Command | Description |
|---------|-------------|
| `acp scan` | Discover and register configured agents |
| `acp list` | List all agents in inventory |
| `acp health [--timeout N]` | Run health checks against all agents |
| `acp cost` | Show estimated monthly costs |
| `acp export --format json/csv [-o PATH]` | Export inventory data |
| `acp status` | Show fleet summary statistics |
| `acp delete <name>` | Remove an agent from inventory |

## Development

### Setup

```bash
uv sync --group dev
```

### Run Tests

```bash
PYTHONPATH="" .venv/bin/python -m pytest tests/ --cov=agent_control_plane
```

### Run Lint

```bash
.venv/bin/python -m ruff check src/ tests/
```

## Architecture

```
                    ┌─────────────┐
                    │   Config    │  YAML file → list of agent endpoints
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
  acp scan ────────►│  Discovery  │──► Register in inventory DB
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
  acp health ───────►   Health   │──► Ping endpoints, log results
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
  acp cost  ───────►   Cost     │──► Estimate spend by provider
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
  acp export ───────►  Export   │──► JSON/CSV output
                    └─────────────┘

  Storage: SQLite at {ACP_HOME}/inventory.db
```

## Roadmap

- [x] Agent discovery and inventory
- [x] Health monitoring with configurable timeouts
- [x] Cost tracking by provider
- [x] CSV/JSON export
- [x] E2E integration tests
- [ ] Web UI dashboard
- [ ] Slack/email alerts on agent status changes
- [ ] Automatic agent discovery (network scan, MCP server detection)
- [ ] Historical trend charts
- [ ] Multi-user/team support
- [ ] Prometheus metrics endpoint
- [ ] Agent configuration drift detection

## License

MIT — see [LICENSE](LICENSE).

## Author

iknowkungfubar — hello@turintech.solutions
