# Agent Control Plane

**AI Agent Operations Platform** — discover, inventory, monitor, and track costs for AI agents across your organization.

[![Tests](https://github.com/iknowkungfubar/agent-control-plane/actions/workflows/ci.yml/badge.svg)](https://github.com/iknowkungfubar/agent-control-plane/actions)
[![Coverage](https://img.shields.io/badge/coverage-70%25-yellow)](https://github.com/iknowkungfubar/agent-control-plane)
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
- **Alerts & Notifications** — Slack, Discord, webhook, and email alert delivery with history tracking
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
| **DRIFT** | Configuration drift detected on an agent |
| **TEST** | Test notification sent to verify channel configuration |

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
    discord:
      enabled: true
      url: "https://discord.com/api/webhooks/..."
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

### Test Notifications

Send a test message to verify your channel configuration:

```bash
acp notify test
acp notify test --webhook-url "https://hooks.example.com/alert"
acp notify test --slack-url "https://hooks.slack.com/services/..." --discord-url "https://discord.com/api/webhooks/..."
```

### Notification History

View delivery history from the CLI:

```bash
acp notify list
acp notify list --channel slack --agent my-agent
acp notify list --type DOWN --limit 50
```

Or from the dashboard at `/notifications` — filter by channel, agent, alert type, and delivery status.

### Dashboard Notification Settings

Configure notification channels from the web UI at `/notification-settings`. Enable/disable channels and update webhook URLs without editing the config file.

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
| Fleet Status | `/` | Summary cards + fleet health trend chart + recent agents table |
| Agents | `/agents` | Full agent list with status, response time, tags |
| Agent Detail | `/agents/{name}` | Per-agent info + health status stacked chart + response time trend |
| Costs | `/costs` | Monthly cost breakdown + cost trend bar chart |

### API Endpoints

The dashboard server also exposes a REST API:

| Endpoint | Returns |
|----------|---------|
| `GET /api/status` | Fleet summary (counts, total cost) |
| `GET /api/agents` | All agents with status and metadata |
| `GET /api/agents/{name}/health` | Health check history for one agent |
| `GET /api/costs` | Per-agent cost breakdown |
| `GET /api/export` | Full inventory as JSON download |
| `GET /api/alerts?limit=N&agent=X` | Alert history (optionally filtered by agent) |
| `GET /api/analytics/health` | Fleet health time-series (hour/day/week buckets) |
| `GET /api/analytics/health/{name}` | Per-agent health time-series |
| `GET /api/analytics/costs?months=N&agent=X` | Cost time-series by month |

All endpoints return JSON and are suitable for integration with monitoring tools.

### Historical Trend Charts

The dashboard includes Canvas-based (zero-dependency) trend charts:

- **Fleet Status page** — stacked bar chart showing online/offline/degraded distribution over 7 days + average response time line chart
- **Agent Detail page** — per-agent stacked health trend + response time trend
- **Costs page** — monthly cost history bar chart

Charts render with device pixel ratio support, dark-theme styling, and auto-refresh alongside dashboard data.

### Data Retention

Health log records are automatically cleaned up to prevent unbounded database growth:

| Setting | Default | Description |
|---------|---------|-------------|
| `health_log_retention_days` in config.yaml | 90 | Max age in days for health check records |
| `ACP_HEALTH_RETENTION_DAYS` env var | — | Overrides config value |

## Configuration Drift Detection

Agent Control Plane can detect when an agent's actual configuration diverges from its expected baseline — provider changes, version drift, tag changes, or configuration anomalies.

### Managing Baselines

```bash
# Capture a baseline from a live agent (auto-detects version and config)
acp config-baseline capture my-agent

# Manually set expected values
acp config-baseline set my-agent --provider openai --version gpt-4 --tags prod,llm

# View an agent's baseline
acp config-baseline show my-agent

# List all baselines
acp config-baseline list

# Delete a baseline
acp config-baseline delete my-agent
```

### Checking for Drift

```bash
# Check all agents for configuration drift
acp drift-check
# ✓ agent-1: no drift detected
# ⚠ agent-2: 2 drift(s), max severity: high
#   • Provider changed from 'openai' to 'anthropic'
#   • Version changed from 'gpt-4' to 'gpt-3.5'

# Check a specific agent
acp drift-check --name my-agent

# View drift history
acp drift-report
```

### Drift Severity Levels

| Severity | Meaning |
|----------|---------|
| **none** | Config matches baseline |
| **low** | Minor change (version upgrade) |
| **medium** | Notable change (tag or path change) |
| **high** | Significant change (provider change) |
| **critical** | Agent unreachable for verification |

### How It Works

1. **Baseline capture** — `acp config-baseline capture` probes the agent's health endpoint and records expected values (provider, version, tags, metadata).
2. **Drift check** — `acp drift-check` compares current agent state against the stored baseline for each field.
3. **Alert integration** — When drift is detected, a `DRIFT` alert fires through the configured notification channels (Slack, email, webhook).
4. **Dashboard** — Each agent's detail page shows drift event history with severity badges.

## Users & Teams

Agent Control Plane supports multi-user operation with API key authentication
and team-based access control.

### Single-User Mode

By default (no users configured), ACP runs in **single-user mode** with no
authentication required. This preserves backward compatibility.

### Managing Users

```bash
# Create a user (shows API key once)
acp user create alice --email alice@example.com --role admin

# List users
acp user list

# Delete a user
acp user delete alice
```

### Managing Teams

```bash
# Create a team
acp team create infra --name "Infrastructure" --desc "Infra team"

# List teams
acp team list

# Add a user to a team
acp team add-member infra --user alice --role operator

# Remove a user from a team
acp team remove-member infra --user alice

# Assign an agent to a team
acp team add-agent infra --agent my-agent

# Remove an agent from a team
acp team remove-agent --agent my-agent
```

### Dashboard Login

1. Navigate to `/login` on the dashboard
2. Enter your email and API key
3. Signed-in users see their name/role in the sidebar
4. Admin users can access `/admin` for user/team management

### User Roles

| Role | Permissions |
|------|------------|
| **admin** | Full access to all teams, user management, team management |
| **operator** | Manage agents within assigned teams |
| **viewer** | Read-only access to assigned team agents |

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
- [x] Historical trend charts (health time-series + cost trend with Canvas charts)
- [x] Data retention (configurable health log cleanup)
- [x] Agent configuration drift detection (baselines, drift checking, alerts, dashboard display)
- [x] Multi-user/team support (API key auth, team scoping, dashboard login, admin panel)

## License

MIT — see [LICENSE](LICENSE).

## Author

iknowkungfubar — hello@turintechsolutions.com