"""Analytics — time-series aggregation queries for health and cost data.

Provides bucketed aggregation of health log data for trend visualization.
Supports hour / day / week granularity with configurable lookback windows.
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3


def get_health_timeseries(
    conn: sqlite3.Connection,
    agent_name: str,
    bucket: str = "day",
    days: int = 7,
) -> list[dict[str, Any]]:
    """Get health status time-series aggregated by time bucket for one agent.

    Args:
        conn: Database connection.
        agent_name: Name of the agent to query.
        bucket: Time bucket — 'hour', 'day', or 'week'. Defaults to 'day'.
        days: Lookback window in days from now. Defaults to 7.

    Returns:
        List of dicts, each with keys: bucket, online, offline, degraded,
        unknown, count, avg_response_ms, min_response_ms, max_response_ms.
        Ordered from oldest to newest.

    """
    _validate_bucket(bucket)
    fmt = _bucket_format(bucket)

    query = f"""
        SELECT
            strftime('{fmt}', timestamp) AS bucket,
            SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online,
            SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) AS offline,
            SUM(CASE WHEN status = 'degraded' THEN 1 ELSE 0 END) AS degraded,
            SUM(CASE WHEN status = 'unknown' THEN 1 ELSE 0 END) AS unknown,
            COUNT(*) AS count,
            ROUND(AVG(response_time_ms), 2) AS avg_response_ms,
            ROUND(MIN(response_time_ms), 2) AS min_response_ms,
            ROUND(MAX(response_time_ms), 2) AS max_response_ms
        FROM health_log
        WHERE agent_name = ?
          AND timestamp >= datetime('now', '-' || ? || ' days', 'utc')
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    rows = conn.execute(query, (agent_name, str(days))).fetchall()
    return [dict(r) for r in rows]


def get_fleet_health_timeseries(
    conn: sqlite3.Connection,
    bucket: str = "day",
    days: int = 7,
) -> list[dict[str, Any]]:
    """Get fleet-level health time-series aggregated across all agents.

    Args:
        conn: Database connection.
        bucket: Time bucket — 'hour', 'day', or 'week'. Defaults to 'day'.
        days: Lookback window in days from now. Defaults to 7.

    Returns:
        List of dicts, each with keys: bucket, online, offline, degraded,
        unknown, count, total_agents, avg_response_ms.

    """
    _validate_bucket(bucket)
    fmt = _bucket_format(bucket)

    query = f"""
        SELECT
            strftime('{fmt}', timestamp) AS bucket,
            SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online,
            SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) AS offline,
            SUM(CASE WHEN status = 'degraded' THEN 1 ELSE 0 END) AS degraded,
            SUM(CASE WHEN status = 'unknown' THEN 1 ELSE 0 END) AS unknown,
            COUNT(*) AS count,
            (SELECT COUNT(*) FROM agents) AS total_agents,
            ROUND(AVG(response_time_ms), 2) AS avg_response_ms
        FROM health_log
        WHERE timestamp >= datetime('now', '-' || ? || ' days', 'utc')
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    rows = conn.execute(query, (str(days),)).fetchall()
    return [dict(r) for r in rows]


def get_cost_timeseries(
    conn: sqlite3.Connection,
    months: int = 6,
    agent_name: str | None = None,
) -> list[dict[str, Any]]:
    """Get cost time-series data grouped by month.

    Args:
        conn: Database connection.
        months: Number of months to look back. Defaults to 6.
        agent_name: Optional filter to a single agent.

    Returns:
        List of dicts, each with keys: month, total_cost, agents (list of
        {name, cost}). Ordered from oldest to newest.

    """
    min_month = _months_ago(months)

    if agent_name:
        rows = conn.execute(
            """
            SELECT month, estimated_cost_usd
            FROM cost_records
            WHERE month >= ? AND agent_name = ?
            ORDER BY month ASC
            """,
            (min_month, agent_name),
        ).fetchall()
        return [
            {
                "month": r["month"],
                "total_cost": r["estimated_cost_usd"],
                "agents": [{"name": agent_name, "cost": r["estimated_cost_usd"]}],
            }
            for r in rows
        ]

    rows = conn.execute(
        """
        SELECT month, agent_name, estimated_cost_usd
        FROM cost_records
        WHERE month >= ?
        ORDER BY month ASC, agent_name ASC
        """,
        (min_month,),
    ).fetchall()

    # Group by month
    months_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        m = r["month"]
        if m not in months_map:
            months_map[m] = {"month": m, "total_cost": 0.0, "agents": []}
        months_map[m]["total_cost"] += r["estimated_cost_usd"]
        months_map[m]["agents"].append({"name": r["agent_name"], "cost": r["estimated_cost_usd"]})

    return list(months_map.values())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_bucket(bucket: str) -> None:
    """Warn on invalid bucket (silently default to 'day' for resilience)."""
    if bucket not in ("hour", "day", "week"):
        import warnings
        warnings.warn(f"Invalid bucket: '{bucket}'. Defaulting to 'day'.", stacklevel=2)


def _bucket_format(bucket: str) -> str:
    """Return the strftime format string for the given bucket."""
    if bucket == "hour":
        return "%Y-%m-%dT%H:00:00"
    if bucket == "day":
        return "%Y-%m-%d"
    if bucket == "week":
        return "%Y-%W"
    # Should not reach here due to validation, but be safe
    return "%Y-%m-%d"


def _months_ago(n: int) -> str:
    """Return a 'YYYY-MM' string for N months ago from today."""
    from datetime import datetime

    now = datetime.now(UTC)
    year = now.year
    month = now.month - n
    while month < 1:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}"
