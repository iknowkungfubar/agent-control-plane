"""Data models for the Agent Control Plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal


class AgentStatus(str, Enum):
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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentRecord:
    """Persistent record of an agent in the inventory."""

    name: str
    url: str
    provider: AgentProvider
    status: AgentStatus = AgentStatus.UNKNOWN
    tags: list[str] = field(default_factory=list)
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_checks: int = 0
    successful_checks: int = 0
    avg_response_time_ms: float = 0.0


@dataclass
class CostRecord:
    """Estimated cost record for an agent."""

    agent_name: str
    month: str  # "2026-07"
    estimated_tokens_in: int = 0
    estimated_tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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
