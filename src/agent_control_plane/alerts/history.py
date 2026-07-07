"""Alert history — persists alerts to SQLite for querying."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_control_plane.inventory import get_connection


def record_alert(
    agent_name: str,
    alert_type: str,
    status: str,
    message: str,
) -> None:
    """Record an alert in the database history."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO alert_history (agent_name, alert_type, status, message, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            agent_name,
            alert_type,
            status,
            message,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_alert_history(
    agent_name: str | None = None,
    alert_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query alert history with optional filters.

    Args:
        agent_name: Filter by agent name.
        alert_type: Filter by alert type (DOWN, DEGRADED, RECOVERY).
        limit: Max results (default 50).
        offset: Pagination offset.

    Returns:
        List of alert record dicts.
    """
    conn = get_connection()
    conditions: list[str] = []
    params: list[Any] = []

    if agent_name:
        conditions.append("agent_name = ?")
        params.append(agent_name)
    if alert_type:
        conditions.append("alert_type = ?")
        params.append(alert_type)

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM alert_history{where_clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(r) for r in rows]
