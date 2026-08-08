"""Alert notification formatters — Slack blocks and email (backward compat).

Formatting helpers moved to ``notifications.senders``; this module keeps
``format_slack`` and re-exports ``format_email`` for existing callers.
"""

from __future__ import annotations

from typing import Any

from agent_control_plane.notifications.senders import format_email

__all__ = ["format_email", "format_slack"]


def format_slack(
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
