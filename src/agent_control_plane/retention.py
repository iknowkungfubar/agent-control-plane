"""Data retention — configurable cleanup of old health log records.

Automatically removes records older than a configurable retention period
to prevent unbounded database growth.
"""

from __future__ import annotations

import os
import sqlite3


def enforce_retention(conn: sqlite3.Connection, retention_days: int | None = None) -> int:
    """Delete health log records older than the retention period.

    Args:
        conn: Database connection.
        retention_days: Max age in days. If None, read from config.

    Returns:
        Number of deleted records.
    """
    if retention_days is None:
        retention_days = get_retention_days()

    cursor = conn.execute(
        "DELETE FROM health_log WHERE timestamp < datetime('now', '-' || ? || ' days', 'utc')",
        (str(retention_days),),
    )
    deleted = cursor.rowcount
    if deleted > 0:
        conn.commit()
    return deleted


def get_retention_days() -> int:
    """Read the health_log_retention_days setting from config or env.

    Resolution order:
        1. ACP_HEALTH_RETENTION_DAYS environment variable
        2. Config file's health_log_retention_days setting
        3. Default: 90 days
    """
    # Env override first
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
        cfg_days = cfg.get("health_log_retention_days", 90)
        if isinstance(cfg_days, int) and cfg_days > 0:
            return cfg_days
    except (FileNotFoundError, Exception):
        pass

    return 90
