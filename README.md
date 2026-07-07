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
- **Web Dashboard** — Real-time browser UI with fleet status, agent list, health history, and cost breakdown
- **Export** — CSV and JSON export for compliance reporting
- **CLI Interface** — All operations available from the terminal including `acp dashboard`

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
| `acp dashboard [--host HOST] [--port PORT]` | Start the web UI dashboard |
| `acp discover [--host HOST] [--ports PORTS] [--register]` | Auto-discover AI agents on a host |

## Auto-Discovery

Instead of manually listing every agent in the config file, `acp discover` scans hosts for running agent endpoints.

```bash
# Scan localhost for common agent ports
acp discover

# Scan a specific host with custom ports
acp discover --host 192.168.1.100 --ports 11434,8080,8000

# Scan a port range
acp discover --host 10.0.0.50 --ports 8000-8010

# Discover and register in one command
acp discover --host 127.0.0.1 --register --timeout 1.5
```

### How It Works

The discovery engine probes each port by making HTTP requests to known paths:

| Path | What it checks |
|------|---------------|
| `/v1/models` | OpenAI-compatible API |
| `/v1/chat/completions` | OpenAI-compatible |
| `/v1/messages` | Anthropic API |
| `/api/tags` | Ollama |
| `/mcp` | MCP servers |
| `/health` | Generic health endpoint |

Found agents include auto-generated names, detected provider types, and response metadata. Use `--register` to add them to inventory.

### Discovery Configuration

Scan behavior can be customized in `config.yaml`:

```yaml
discovery:
  default_ports: [11434, 8080, 8000, 5000, 3000, 8337, 9090]
  timeout: 2.0
  exclude: ["192.168.1.1", "10.0.0.*"]  # Skip patterns
```

## Alerts & Notifications

Agent Control Plane can automatically notify you when agents change status.

### Alert Types

| Type | When |
|------|------|
| **DOWN** | Agent transitions from online → offline, or consecutive failures exceed threshold |
| **DEGRADED** | Agent transitions from online → degraded |
| **RECOVERY** | Agent recovers from offline/degraded → online |

### Configuration

```yaml
# config.yaml
agents:
  - name: my-agent
    url: http://localhost:8080
    alerts:
      consecutive_failures: 5         # Per-agent override (default: 3)
      rate_limit_seconds: 600         # Per-agent override (default: 300)

alerts:
  enabled: true
  global:
    consecutive_failures: 3           # Alert after N consecutive failures
    rate_limit_seconds: 300           # Max 1 alert per N seconds per agent
  channels:
    webhook:
      enabled: true
      url: "https://hooks.example.com/alerts"
    slack:
      enabled: true
      url: "https://hooks.slack.com/services/..."
    email:
      enabled: true
      smtp_host: "smtp.gmail.com"
      smtp_port: 587
      smtp_user: "user@gmail.com"
      smtp_password: "app-password"
      from: "acp@example.com"
      recipients:
        - "ops@example.com"
```

### Alert History API

GET `/api/alerts?limit=50&agent=my-agent` returns recent alerts.

## Prometheus Metrics

The dashboard exposes a `/metrics` endpoint in Prometheus text format:

```bash
curl http://localhost:8337/metrics
# HELP acp_agent_online Current online status of AI agents (1=online, 0=offline)
# TYPE acp_agent_online gauge
acp_agent_online{name="my-agent",provider="openai"} 1
# HELP acp_agent_response_ms Average response time in milliseconds
# TYPE acp_agent_response_ms gauge
acp_agent_response_ms{name="my-agent"} 45.2
# HELP acp_fleet_agents_total Total number of agents in inventory
# TYPE acp_fleet_agents_total gauge
acp_fleet_agents_total 3
```

### Available Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `acp_agent_online` | gauge | 1 if agent is online, 0 otherwise |
| `acp_agent_response_ms` | gauge | Average response time per agent |
| `acp_agent_checks_total` | counter | Total health checks performed |
| `acp_agent_checks_successful` | counter | Successful health checks |
| `acp_fleet_agents_total` | gauge | Total agents in inventory |
| `acp_fleet_monthly_cost_est` | gauge | Estimated monthly cost (USD) |

## Dashboard

The Agent Control Plane includes a browser-based dashboard for real-time fleet visibility.

### Start the Dashboard

```bash
acp dashboard
# Agent Control Plane Dashboard → http://127.0.0.1:8337
```

Then open http://localhost:8337 in your browser.

### Dashboard Pages

| Page | Route | Description |
|------|-------|-------------|
| Fleet Status | `/` | Summary cards (total/online/offline/degraded) + recent agents table |
| Agents | `/agents` | Full agent list with status, response time, tags |
| Agent Detail | `/agents/{name}` | Per-agent info + health history timeline |
| Costs | `/costs` | Monthly cost breakdown per agent with totals |

### API Endpoints

The dashboard server also exposes a REST API:

| Endpoint | Returns |
|----------|---------|
| `GET /api/status` | Fleet summary (counts, total cost) |
| `GET /api/agents` | All agents with status and metadata |
| `GET /api/agents/{name}/health` | Health check history for one agent |
| `GET /api/costs` | Per-agent cost breakdown |
| `GET /api/export` | Full inventory as JSON download |

All endpoints return JSON and are suitable for integration with monitoring tools.

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
- [x] Web UI dashboard (FastAPI + responsive HTML/JS)
- [x] Prometheus metrics endpoint
- [x] Slack/email/webhook alerts on agent status changes
- [x] Automatic agent discovery (port scan + MCP detection)
- [ ] Historical trend charts
- [ ] Multi-user/team support
- [ ] Prometheus metrics endpoint
- [ ] Agent configuration drift detection

## License

MIT — see [LICENSE](LICENSE).

## Author

iknowkungfubar — hello@turintech.solutions
