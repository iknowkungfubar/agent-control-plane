"""Agent Control Plane — Agent Discovery Subsystem."""

# Restore original discovery.py API for backward compatibility
from datetime import UTC

from agent_control_plane.config import load_config, parse_agents
from agent_control_plane.discovery.scanner import probe_endpoint, register_discovered, scan_ports


def get_configured_agents() -> list:
    """Load configured agent endpoints from config (original API)."""
    cfg = load_config()
    return parse_agents(cfg)


def scan_and_report() -> list:
    """Run discovery and report (original API)."""
    return sync_inventory()


def sync_inventory() -> list:
    """Sync configured agents into inventory (original API)."""
    from datetime import datetime, timezone

    from agent_control_plane.inventory import get_connection, list_agents, upsert_agent
    from agent_control_plane.models import AgentRecord, AgentStatus

    cfg = load_config()
    endpoints = parse_agents(cfg)
    conn = get_connection()
    now = datetime.now(UTC)

    for ep in endpoints:
        record = AgentRecord(
            name=ep.name, url=ep.url, provider=ep.provider,
            status=AgentStatus.UNKNOWN, tags=ep.tags,
            first_seen=now, last_seen=now,
        )
        upsert_agent(conn, record)

    conn.close()
    return list_agents(get_connection())


__all__ = [
    "get_configured_agents",
    "probe_endpoint",
    "register_discovered",
    "scan_and_report",
    "scan_ports",
    "sync_inventory",
]
