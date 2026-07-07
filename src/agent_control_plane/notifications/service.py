"""Notification routing service — sends alerts to configured channels.

Routes alert events to all enabled notification channels, records delivery
history, and handles retry for transient failures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_control_plane.inventory import get_connection
from agent_control_plane.notifications.senders import (
    build_webhook_payload,
    format_discord,
    format_slack_blocks,
    send_discord,
    send_slack,
    send_webhook,
)

# Map channel names to (format_fn, send_fn) pairs
_CHANNEL_SENDERS: dict[str, tuple[str, str]] = {
    "webhook": ("build_webhook_payload", "send_webhook"),
    "slack": ("format_slack_blocks", "send_slack"),
    "discord": ("format_discord", "send_discord"),
}


def send_notification(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
    enabled_channels: dict[str, Any] | None = None,
    **extra: Any,
) -> list[dict[str, Any]]:
    """Send an alert notification to all enabled channels.

    Args:
        alert_type: Type of alert (DOWN, DEGRADED, RECOVERY, DRIFT, TEST).
        agent_name: Name of the agent.
        status: Current agent status.
        message: Human-readable alert message.
        enabled_channels: Dict of channel_name -> channel_config.
            If None, loads from alert config.
        **extra: Additional fields to include in the payload.

    Returns:
        List of delivery result dicts, one per channel, each with keys:
        channel, success, status_code, error.
    """
    if enabled_channels is None:
        from agent_control_plane.alerts.rules import load_alert_config

        cfg = load_alert_config()
        enabled_channels = cfg.get("channels", {})

    results: list[dict[str, Any]] = []

    for channel_name, channel_cfg in enabled_channels.items():
        if not channel_cfg.get("enabled", False):
            continue

        result = _dispatch_to_channel(
            channel_name=channel_name,
            channel_cfg=channel_cfg,
            alert_type=alert_type,
            agent_name=agent_name,
            status=status,
            message=message,
            **extra,
        )
        results.append(result)

        # Record delivery in notification history
        _record_notification(
            channel=channel_name,
            alert_type=alert_type,
            agent_name=agent_name,
            status=status,
            message=message[:500],  # Truncate for storage
            success=result["success"],
            error=result.get("error"),
        )

    return results


def _dispatch_to_channel(
    channel_name: str,
    channel_cfg: dict[str, Any],
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    """Dispatch an alert to a single notification channel.

    Returns a result dict with channel, success, status_code, error.
    """
    url = channel_cfg.get("url", "")

    if channel_name == "webhook":
        payload = build_webhook_payload(alert_type, agent_name, status, message, **extra)
        headers = channel_cfg.get("headers")
        result = send_webhook(url, payload, headers=headers)

    elif channel_name == "slack":
        payload = format_slack_blocks(alert_type, agent_name, status, message)
        result = send_slack(url, payload)

    elif channel_name == "discord":
        payload = format_discord(alert_type, agent_name, status, message)
        result = send_discord(url, payload)

    else:
        return {"success": False, "status_code": None, "error": f"Unknown channel: {channel_name}"}

    result["channel"] = channel_name
    return result


def _record_notification(
    channel: str,
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
    success: bool,
    error: str | None = None,
) -> None:
    """Record a notification delivery in the history table.

    This is a fire-and-forget operation — failures to record are logged
    but not propagated.
    """
    try:
        conn = get_connection()
        conn.execute(
            """INSERT INTO notification_history
               (channel, alert_type, agent_name, status, message, success, error, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (channel, alert_type, agent_name, status, message, int(success), error,
             datetime.now(UTC).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to record notification history")


def get_notification_history(
    channel: str | None = None,
    agent_name: str | None = None,
    alert_type: str | None = None,
    success: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Get notification delivery history with optional filters.

    Args:
        channel: Filter by notification channel.
        agent_name: Filter by agent name.
        alert_type: Filter by alert type.
        success: Filter by delivery success.
        limit: Max results (default 50).
        offset: Pagination offset.

    Returns:
        List of notification history dicts.
    """
    conn = get_connection()
    conditions: list[str] = []
    params: list[Any] = []

    if channel:
        conditions.append("channel = ?")
        params.append(channel)
    if agent_name:
        conditions.append("agent_name = ?")
        params.append(agent_name)
    if alert_type:
        conditions.append("alert_type = ?")
        params.append(alert_type)
    if success is not None:
        conditions.append("success = ?")
        params.append(int(success))

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM notification_history{where_clause} ORDER BY sent_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def get_notification_summary() -> dict[str, Any]:
    """Get notification summary counts."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT channel, COUNT(*) as cnt FROM notification_history WHERE success = 1 GROUP BY channel"
    ).fetchall()
    by_channel: dict[str, int] = {r["channel"]: r["cnt"] for r in rows}

    fail_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM notification_history WHERE success = 0"
    ).fetchone()

    total_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM notification_history"
    ).fetchone()
    conn.close()

    return {
        "total": total_row["cnt"] if total_row else 0,
        "failed": fail_row["cnt"] if fail_row else 0,
        "by_channel": by_channel,
    }


def send_test_notification(
    agent_name: str = "test-agent",
    webhook_url: str | None = None,
    slack_url: str | None = None,
    discord_url: str | None = None,
) -> list[dict[str, Any]]:
    """Send a test notification to verify channel configuration.

    Args:
        agent_name: Name to use in the test message.
        webhook_url: Override webhook URL.
        slack_url: Override Slack webhook URL.
        discord_url: Override Discord webhook URL.

    Returns:
        List of delivery result dicts.
    """
    channels: dict[str, dict[str, Any]] = {}

    if webhook_url:
        channels["webhook"] = {"enabled": True, "url": webhook_url}
    if slack_url:
        channels["slack"] = {"enabled": True, "url": slack_url}
    if discord_url:
        channels["discord"] = {"enabled": True, "url": discord_url}

    if not channels:
        # Try loading from config
        from agent_control_plane.alerts.rules import load_alert_config

        cfg = load_alert_config()
        channels = {
            name: ch
            for name, ch in cfg.get("channels", {}).items()
            if ch.get("enabled", False)
        }

    return send_notification(
        alert_type="TEST",
        agent_name=agent_name,
        status="online",
        message=f"Test notification from Agent Control Plane — {agent_name}",
        enabled_channels=channels,
    )
