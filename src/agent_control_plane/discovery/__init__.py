"""Agent Control Plane — Agent Discovery Subsystem."""

from agent_control_plane.discovery.scanner import probe_endpoint, scan_ports, register_discovered

# Restore original discovery.py API for backward compatibility
from agent_control_plane.config import load_config, parse_agents


def get_configured_agents() -> list:
    """Load configured agent endpoints from config (original API)."""
    cfg = load_config()
    return parse_agents(cfg)


def scan_and_report() -> list:
    """Run discovery and report (original API)."""
    return sync_inventory()


def sync_inventory() -> list:
    """Sync configured agents into inventory (original API)."""
    from agent_control_plane.inventory import get_connection, upsert_agent, list_agents
    from datetime import datetime, timezone
    from agent_control_plane.models import AgentRecord, AgentStatus

    cfg = load_config()
    endpoints = parse_agents(cfg)
    conn = get_connection()
    now = datetime.now(timezone.utc)

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
    "probe_endpoint", "scan_ports", "register_discovered",
    "scan_and_report", "get_configured_agents", "sync_inventory",
]
