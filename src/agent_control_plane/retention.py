"""Data retention — configurable cleanup of old log records.

Automatically removes records older than a configurable retention period
from health, alert, notification, and drift tables to prevent unbounded
database growth.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

# Tables subject to retention: {table: (timestamp_column, config_key)}
_RETENTION_TABLES: dict[str, tuple[str, str]] = {
    "health_log": ("timestamp", "health_log_retention_days"),
    "alert_history": ("timestamp", "alert_history_retention_days"),
    "notification_history": ("sent_at", "notification_history_retention_days"),
    "drift_log": ("detected_at", "drift_log_retention_days"),
}


def enforce_retention(conn: sqlite3.Connection, retention_days: int | None = None) -> int:
    """Delete records older than the retention period from all tracked tables.

    Args:
        conn: Database connection.
        retention_days: Max age in days applied to every table. If None,
            each table uses its own configured retention period.

    Returns:
        Total number of deleted records across all tables.

    """
    total_deleted = 0
    for table, (column, _key) in _RETENTION_TABLES.items():
        days = retention_days if retention_days is not None else get_retention_days(table)
        total_deleted += _delete_old_records(conn, table, column, days)
    return total_deleted


def _delete_old_records(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    days: int,
) -> int:
    """Delete records from one table older than ``days`` days."""
    cursor = conn.execute(
        f"DELETE FROM {table} WHERE {column} < datetime('now', '-' || ? || ' days', 'utc')",  # noqa: S608
        (str(days),),
    )
    deleted = cursor.rowcount
    if deleted > 0:
        conn.commit()
    return deleted


def get_retention_days(table: str | None = None) -> int:
    """Read the retention period for a table from config or env.

    Resolution order:
        1. ACP_HEALTH_RETENTION_DAYS environment variable (health_log only)
        2. Config file's ``retention: {table}_days`` section
        3. Legacy top-level ``health_log_retention_days`` key (health_log only)
        4. Default: 90 days

    Args:
        table: Table name to look up. Defaults to 'health_log'.

    Returns:
        Retention period in days.

    """
    table = table or "health_log"

    # Env override for health_log only (legacy)
    if table == "health_log":
        env_val = os.environ.get("ACP_HEALTH_RETENTION_DAYS")
        if env_val is not None:
            try:
                return max(1, int(env_val))
            except (ValueError, TypeError):
                pass

    # Config file
    try:
        from agent_control_plane.config import load_config

        cfg = load_config()
        ret_cfg = cfg.get("retention", {}) or {}
        cfg_days = ret_cfg.get(f"{table}_days")

        # Legacy top-level key for health_log
        if cfg_days is None and table == "health_log":
            cfg_days = cfg.get("health_log_retention_days")

        if isinstance(cfg_days, int) and cfg_days > 0:
            return cfg_days
        if isinstance(cfg_days, (str, float)):  # tolerate "90" / 90.0 in YAML
            try:
                days = int(cfg_days)
                if days > 0:
                    return days
            except (ValueError, TypeError):
                pass
    except (FileNotFoundError, ValueError, TypeError):
        pass

    return 90
