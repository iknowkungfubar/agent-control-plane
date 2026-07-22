"""Data models for the Agent Control Plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class AgentStatus(StrEnum):
    """Health status of an agent endpoint."""

    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"


AgentProvider = Literal[
    "openai",
    "anthropic",
    "google",
    "mistral",
    "ollama",
    "lm-studio",
    "opencode",
    "custom",
]


@dataclass
class AgentEndpoint:
    """Configuration for an agent endpoint to monitor."""

    name: str
    url: str
    provider: AgentProvider = "custom"
    health_check_path: str = "/health"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def health_url(self) -> str:
        """Full URL for health checking."""
        base = self.url.rstrip("/")
        path = self.health_check_path.lstrip("/")
        return f"{base}/{path}"


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    agent_name: str
    status: AgentStatus
    response_time_ms: float
    status_code: int | None
    error: str | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AgentRecord:
    """Persistent record of an agent in the inventory."""

    name: str
    url: str
    provider: AgentProvider
    status: AgentStatus = AgentStatus.UNKNOWN
    tags: list[str] = field(default_factory=list)
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    total_checks: int = 0
    successful_checks: int = 0
    avg_response_time_ms: float = 0.0
    team_id: str | None = None


@dataclass
class CostRecord:
    """Estimated cost record for an agent."""

    agent_name: str
    month: str  # "2026-07"
    estimated_tokens_in: int = 0
    estimated_tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


class UserRole(StrEnum):
    """Role for a user in the system."""

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


@dataclass
class User:
    """A user of the ACP system."""

    name: str
    email: str
    role: UserRole = UserRole.VIEWER
    api_key_hash: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime | None = None


@dataclass
class Team:
    """A team that groups agents and users."""

    id: str  # short unique id
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class TeamMember:
    """Membership of a user in a team with a role."""

    user_name: str
    team_id: str
    role_in_team: UserRole = UserRole.VIEWER


@dataclass
class ConfigBaseline:
    """Expected configuration baseline for an agent."""

    agent_name: str
    provider: str
    health_check_path: str = "/health"
    expected_version: str | None = None
    expected_tags: list[str] = field(default_factory=list)
    additional_fields: dict[str, str] = field(default_factory=dict)
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    captured_by: str = "manual"  # "manual" or "auto"


@dataclass
class DriftCheckResult:
    """Result of comparing actual vs expected config."""

    agent_name: str
    field: str
    expected: str
    actual: str
    severity: str  # "none", "low", "medium", "high", "critical"
    message: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DriftSeverity(StrEnum):
    """Severity of configuration drift."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DriftReport:
    """Full drift detection report for an agent."""

    agent_name: str
    has_baseline: bool
    drift_count: int
    max_severity: DriftSeverity
    results: list[DriftCheckResult]
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class DriftRecord:
    """Persistent record of a drift detection event."""

    id: int | None = None
    agent_name: str = ""
    field_name: str = ""
    expected: str = ""
    actual: str = ""
    severity: str = "medium"
    message: str = ""
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SummaryStats:
    """Aggregate statistics about the agent fleet."""

    total_agents: int
    online: int
    offline: int
    degraded: int
    unknown: int
    total_estimated_cost_monthly_usd: float
    total_checks_run: int


class ShadowRisk(StrEnum):
    """Risk level for a discovered shadow IT service."""

    CRITICAL = "critical"  # Data exfiltration risk, no auth
    HIGH = "high"  # Known vulnerabilities, unapproved
    MEDIUM = "medium"  # Shadow IT, but some controls
    LOW = "low"  # Sanctioned or low-risk service
    UNKNOWN = "unknown"


class ShadowCategory(StrEnum):
    """Category of shadow IT service."""

    AI_API = "ai-api"
    SELF_HOSTED_LLM = "self-hosted-llm"
    CODING_AGENT = "coding-agent"
    AI_BROWSER = "ai-browser"
    VECTOR_DB = "vector-db"
    MCP_SERVER = "mcp-server"
    AI_DEV_TOOL = "ai-dev-tool"
    BROWSER_EXTENSION = "browser-extension"
    SAAS_APP = "saas-app"
    UNKNOWN = "unknown"


@dataclass
class ShadowFingerprint:
    """A detection signature for a known AI/SaaS service."""

    name: str
    category: ShadowCategory
    paths: list[str]  # URL paths to probe
    body_patterns: list[str]  # Strings to match in response body
    header_patterns: dict[str, str]  # {header_name: expected_value_pattern}
    port_hints: list[int]  # Common ports
    risk: ShadowRisk = ShadowRisk.MEDIUM
    description: str = ""


@dataclass
class ShadowService:
    """A discovered shadow IT service in the catalog."""

    id: int | None = None
    name: str = ""
    url: str = ""
    service_type: str = "unknown"  # Matches ShadowCategory value
    risk: str = "unknown"  # Matches ShadowRisk value
    host: str = ""
    port: int = 0
    discovered_by: str = ""  # "port_scan", "dns_analysis", "proxy"
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
