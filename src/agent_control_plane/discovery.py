"""Agent discovery engine — detects and registers agent endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from agent_control_plane.config import load_config, parse_agents
from agent_control_plane.inventory import (
    get_connection,
    list_agents,
    upsert_agent,
)
from agent_control_plane.models import AgentEndpoint, AgentRecord, AgentStatus


def get_configured_agents() -> list[AgentEndpoint]:
    """Load agent endpoints from config file.

    Returns:
        List of configured agent endpoints.

    Raises:
        FileNotFoundError: If config file is missing.
    """
    cfg = load_config()
    return parse_agents(cfg)


def sync_inventory() -> list[AgentRecord]:
    """Synchronize configured agents into the inventory database.

    New agents are added with UNKNOWN status. Existing agents are updated
    with any config changes (URL, provider, tags).

    Returns:
        Current list of all agents in inventory.
    """
    endpoints = get_configured_agents()
    conn = get_connection()
    now = datetime.now(timezone.utc)

    for ep in endpoints:
        existing = _find_in_db(conn, ep.name)
        record = AgentRecord(
            name=ep.name,
            url=ep.url,
            provider=ep.provider,
            status=existing.status if existing else AgentStatus.UNKNOWN,
            tags=ep.tags,
            first_seen=existing.first_seen if existing else now,
            last_seen=now,
            total_checks=existing.total_checks if existing else 0,
            successful_checks=existing.successful_checks if existing else 0,
            avg_response_time_ms=existing.avg_response_time_ms if existing else 0.0,
        )
        upsert_agent(conn, record)

    conn.close()
    return list_agents(get_connection())


def _find_in_db(conn, name: str) -> AgentRecord | None:
    """Check if an agent already exists in the DB."""
    from agent_control_plane.inventory import get_agent
    return get_agent(conn, name)


def scan_and_report() -> list[AgentRecord]:
    """Run a full scan: sync config agents, return inventory.

    Returns:
        Updated list of agent records.
    """
    return sync_inventory()
