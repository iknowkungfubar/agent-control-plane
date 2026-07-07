"""Notification channel senders — formats and sends to webhook, Slack, Discord.

Each sender is a standalone function that takes alert fields and returns
a dict with 'success' and optionally 'error' keys.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Webhook sender
# ---------------------------------------------------------------------------


def build_webhook_payload(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    """Build a generic JSON payload for webhook delivery.

    Returns a flat dict with standard alert fields.
    """
    return {
        "type": alert_type,
        "agent_name": agent_name,
        "status": status,
        "message": message,
        **_timestamp(),
        **extra,
    }


def send_webhook(
    url: str,
    payload: dict[str, Any],
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """POST a JSON payload to a webhook URL.

    Args:
        url: Target webhook URL.
        payload: JSON-serializable dict.
        timeout: HTTP timeout in seconds.
        headers: Optional custom headers.

    Returns:
        Dict with keys: success (bool), status_code (int or None),
        error (str or None).
    """
    if not url:
        return {"success": False, "status_code": None, "error": "No URL configured"}

    default_headers = {"Content-Type": "application/json"}
    if headers:
        default_headers.update(headers)

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=default_headers)
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "error": None}
    except httpx.TimeoutException:
        return {"success": False, "status_code": None, "error": "Request timed out"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "status_code": e.response.status_code, "error": str(e)}
    except httpx.RequestError as e:
        return {"success": False, "status_code": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Slack sender
# ---------------------------------------------------------------------------


def format_slack_blocks(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    """Format an alert as a Slack message with blocks.

    Returns a Slack-compatible payload dict.
    """
    colors = {
        "DOWN": "danger",
        "DEGRADED": "warning",
        "RECOVERY": "good",
        "DRIFT": "warning",
        "TEST": "good",
    }
    color = colors.get(alert_type, "warning")
    emoji = {
        "DOWN": "🔴",
        "DEGRADED": "🟡",
        "RECOVERY": "✅",
        "DRIFT": "🔧",
        "TEST": "🧪",
    }.get(alert_type, "ℹ️")

    title = f"{emoji} Agent {alert_type}: {agent_name}"

    return {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": message,
                "fields": [
                    {"title": "Agent", "value": agent_name, "short": True},
                    {"title": "Status", "value": status, "short": True},
                    {"title": "Type", "value": alert_type, "short": True},
                ],
                "footer": "Agent Control Plane",
                "ts": __import__("time").time(),
            },
        ],
    }


def send_slack(
    webhook_url: str,
    payload: dict[str, Any],
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST a Slack message to a Slack webhook URL.

    Args:
        webhook_url: Slack incoming webhook URL.
        payload: Slack message payload (from format_slack_blocks).
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with keys: success (bool), status_code (int or None),
        error (str or None).
    """
    if not webhook_url:
        return {"success": False, "status_code": None, "error": "No Slack webhook URL"}

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "error": None}
    except httpx.TimeoutException:
        return {"success": False, "status_code": None, "error": "Request timed out"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "status_code": e.response.status_code, "error": str(e)}
    except httpx.RequestError as e:
        return {"success": False, "status_code": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Discord sender
# ---------------------------------------------------------------------------


def format_discord(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    """Format an alert as a Discord embed message.

    Returns a Discord-compatible payload with embeds.
    """
    colors = {
        "DOWN": 0xFF0000,
        "DEGRADED": 0xFFFF00,
        "RECOVERY": 0x00FF00,
        "DRIFT": 0xFFA500,
        "TEST": 0x5865F2,
    }
    color = colors.get(alert_type, 0xFFFF00)

    emoji = {
        "DOWN": "🔴",
        "DEGRADED": "🟡",
        "RECOVERY": "✅",
        "DRIFT": "🔧",
        "TEST": "🧪",
    }.get(alert_type, "ℹ️")

    return {
        "embeds": [
            {
                "title": f"{emoji} Agent {alert_type}: {agent_name}",
                "description": message,
                "color": color,
                "fields": [
                    {"name": "Agent", "value": agent_name, "inline": True},
                    {"name": "Status", "value": status, "inline": True},
                    {"name": "Type", "value": alert_type, "inline": True},
                ],
                "footer": {"text": "Agent Control Plane"},
                "timestamp": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
            },
        ],
    }


def send_discord(
    webhook_url: str,
    payload: dict[str, Any],
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST a Discord embed message to a Discord webhook URL.

    Args:
        webhook_url: Discord webhook URL.
        payload: Discord message payload (from format_discord).
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with keys: success (bool), status_code (int or None),
        error (str or None).
    """
    if not webhook_url:
        return {"success": False, "status_code": None, "error": "No Discord webhook URL"}

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "error": None}
    except httpx.TimeoutException:
        return {"success": False, "status_code": None, "error": "Request timed out"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "status_code": e.response.status_code, "error": str(e)}
    except httpx.RequestError as e:
        return {"success": False, "status_code": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> dict[str, str]:
    """Return current UTC timestamp as ISO string."""
    from datetime import UTC, datetime

    return {"timestamp": datetime.now(UTC).isoformat()}
