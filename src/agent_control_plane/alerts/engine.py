"""Alert engine — detects agent status transitions and triggers notifications."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from agent_control_plane.alerts.history import record_alert
from agent_control_plane.alerts.rules import get_agent_alert_rules, load_alert_config
from agent_control_plane.inventory import get_agent
from agent_control_plane.models import AgentStatus

# In-memory state tracking
_last_status: dict[str, AgentStatus] = {}
_consecutive_failures: dict[str, int] = {}
_last_alert_time: dict[str, float] = {}  # "{agent_name}:{alert_type}" → timestamp


def _reset_state() -> None:
    """Reset all in-memory state (for testing)."""
    _last_status.clear()
    _consecutive_failures.clear()
    _last_alert_time.clear()


def _reset_config_cache() -> None:
    """Reset config cache (for testing)."""
    from agent_control_plane.alerts.rules import _config_cache
    _config_cache.clear()


def _get_previous_status(agent_name: str) -> AgentStatus:
    """Get the last known status for an agent, or UNKNOWN if first check."""
    if agent_name in _last_status:
        return _last_status[agent_name]
    # Look up in database
    conn = None
    try:
        from agent_control_plane.inventory import get_connection
        conn = get_connection()
        record = get_agent(conn, agent_name)
        if record:
            return record.status
    finally:
        if conn:
            conn.close()
    return AgentStatus.UNKNOWN


def _is_rate_limited(agent_name: str, alert_type: str, rate_limit_sec: int) -> bool:
    """Check if this alert type for this agent is rate-limited."""
    key = f"{agent_name}:{alert_type}"
    last_time = _last_alert_time.get(key, 0)
    if time.time() - last_time < rate_limit_sec:
        return True
    _last_alert_time[key] = time.time()
    return False


def evaluate_alerts(agent_name: str, new_status: AgentStatus) -> list[dict[str, Any]]:
    """Evaluate whether alerts should fire for a status change.

    Args:
        agent_name: The agent being checked.
        new_status: The agent's current (newly observed) status.

    Returns:
        List of alert dicts with keys: type, agent_name, status, message, timestamp.
        Empty list if no alert conditions are met.

    """
    alerts: list[dict[str, Any]] = []
    cfg = load_alert_config()
    if not cfg.get("enabled", True):
        return alerts

    prev_status = _get_previous_status(agent_name)
    _last_status[agent_name] = new_status

    # Track consecutive failures
    if new_status in (AgentStatus.OFFLINE, AgentStatus.DEGRADED):
        _consecutive_failures[agent_name] = _consecutive_failures.get(agent_name, 0) + 1
    else:
        old_failures = _consecutive_failures.get(agent_name, 0)
        if old_failures > 0 and prev_status in (AgentStatus.OFFLINE, AgentStatus.DEGRADED):
            # Recovery
            _consecutive_failures[agent_name] = 0

    rules = get_agent_alert_rules(agent_name)
    threshold = rules.get("consecutive_failures", cfg.get("global", {}).get("consecutive_failures", 3))
    rate_limit = rules.get("rate_limit_seconds", cfg.get("global", {}).get("rate_limit_seconds", 300))

    now = datetime.now(UTC).isoformat()

    # Check for transition-based alerts
    if prev_status != new_status:
        # Machine-readable type for dedup and routing
        if prev_status == AgentStatus.ONLINE and new_status == AgentStatus.OFFLINE:
            alerts.append({
                "type": "DOWN",
                "agent_name": agent_name,
                "status": "offline",
                "message": f"Agent '{agent_name}' went offline (was online)",
                "timestamp": now,
            })
        elif prev_status == AgentStatus.ONLINE and new_status == AgentStatus.DEGRADED:
            alerts.append({
                "type": "DEGRADED",
                "agent_name": agent_name,
                "status": "degraded",
                "message": f"Agent '{agent_name}' degraded (was online)",
                "timestamp": now,
            })
        elif prev_status in (AgentStatus.OFFLINE, AgentStatus.DEGRADED) and new_status == AgentStatus.ONLINE:
            alerts.append({
                "type": "RECOVERY",
                "agent_name": agent_name,
                "status": "online",
                "message": f"Agent '{agent_name}' recovered ({prev_status.value} → online)",
                "timestamp": now,
            })

    # Check for consecutive failure threshold
    consecutive = _consecutive_failures.get(agent_name, 0)
    if consecutive >= threshold and consecutive > 1:
        # Check we haven't already alerted for this threshold crossing
        prev_already = any(
            a["type"] == "DOWN" and a["agent_name"] == agent_name
            for a in alerts
        )
        if not prev_already and new_status in (AgentStatus.OFFLINE, AgentStatus.DEGRADED):
            alerts.append({
                "type": "DOWN",
                "agent_name": agent_name,
                "status": new_status.value,
                "message": f"Agent '{agent_name}' has {consecutive} consecutive failures (threshold: {threshold})",
                "timestamp": now,
            })

    return alerts


def dispatch_alerts(alerts: list[dict[str, Any]]) -> None:
    """Dispatch alerts to configured notification channels."""
    if not alerts:
        return

    from agent_control_plane.alerts.rules import load_alert_config
    cfg = load_alert_config()
    channels = cfg.get("channels", {})
    rate_limit = cfg.get("global", {}).get("rate_limit_seconds", 300)

    for alert in alerts:
        # Rate limit at dispatch level (not generation level)
        if _is_rate_limited(alert["agent_name"], f"dispatch:{alert['type']}", rate_limit):
            continue

        # Record to history
        record_alert(
            agent_name=alert["agent_name"],
            alert_type=alert["type"],
            status=alert["status"],
            message=alert["message"],
        )

        # Dispatch per channel
        for channel_name, channel_cfg in channels.items():
            if not channel_cfg.get("enabled", False):
                continue

            try:
                if channel_name == "webhook":
                    _dispatch_webhook(channel_cfg.get("url", ""), alert)
                elif channel_name == "slack":
                    _dispatch_slack(channel_cfg, alert)
                elif channel_name == "email":
                    _dispatch_email(channel_cfg, alert)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to dispatch alert via %s: %s", channel_name, e,
                )


def dispatch_drift_alert(
    agent_name: str,
    drift_count: int,
    max_severity: str,
    details: str = "",
) -> None:
    """Dispatch a configuration drift alert.

    Args:
        agent_name: The agent with detected drift.
        drift_count: Number of drifted fields.
        max_severity: Highest severity level detected.
        details: Human-readable details of the drift.

    """
    from agent_control_plane.alerts.rules import get_agent_alert_rules, load_alert_config
    cfg = load_alert_config()
    if not cfg.get("enabled", True):
        return

    rules = get_agent_alert_rules(agent_name)
    rate_limit = rules.get("rate_limit_seconds", cfg.get("global", {}).get("rate_limit_seconds", 300))

    now = datetime.now(UTC).isoformat()

    alert = {
        "type": "DRIFT",
        "agent_name": agent_name,
        "status": max_severity,
        "message": f"Agent '{agent_name}' has {drift_count} config drift(s) (max: {max_severity})",
        "timestamp": now,
    }
    if details:
        alert["message"] += f" - {details}"

    # Rate limit DRIFT alerts
    if _is_rate_limited(agent_name, "DRIFT", rate_limit):
        return

    record_alert(
        agent_name=agent_name,
        alert_type="DRIFT",
        status=max_severity,
        message=alert["message"],
    )


def _dispatch_webhook(url: str, alert: dict[str, Any]) -> None:
    """POST alert as JSON to a generic webhook URL."""
    if not url or url == "http://localhost:0/placeholder":
        return
    import httpx
    with httpx.Client(timeout=10) as client:
        client.post(url, json=alert)


def _dispatch_slack(channel_cfg: dict, alert: dict[str, Any]) -> None:
    """Send alert to Slack via webhook."""
    url = channel_cfg.get("url", "")
    if not url:
        return
    from agent_control_plane.alerts.notifications import format_slack
    payload = format_slack(
        alert_type=alert["type"],
        agent_name=alert["agent_name"],
        status=alert["status"],
        message=alert["message"],
    )
    import httpx
    with httpx.Client(timeout=10) as client:
        client.post(url, json=payload)


def _dispatch_email(channel_cfg: dict, alert: dict[str, Any]) -> None:
    """Send alert via SMTP email."""
    recipients = channel_cfg.get("recipients", [])
    if not recipients:
        return
    from agent_control_plane.alerts.notifications import format_email, send_email
    subject, body = format_email(
        alert_type=alert["type"],
        agent_name=alert["agent_name"],
        status=alert["status"],
        message=alert["message"],
    )
    send_email(
        recipients=recipients,
        subject=subject,
        body=body,
        smtp_host=channel_cfg.get("smtp_host", "localhost"),
        smtp_port=channel_cfg.get("smtp_port", 25),
        smtp_user=channel_cfg.get("smtp_user"),
        smtp_password=channel_cfg.get("smtp_password"),
        from_addr=channel_cfg.get("from", "acp@localhost"),
    )
