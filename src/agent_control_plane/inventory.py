"""Inventory database — SQLite storage for agent records."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_control_plane.models import (
    AgentRecord,
    AgentStatus,
    ConfigBaseline,
    CostRecord,
    DriftRecord,
    SummaryStats,
)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Create database tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            name            TEXT PRIMARY KEY,
            url             TEXT NOT NULL,
            provider        TEXT NOT NULL DEFAULT 'custom',
            status          TEXT NOT NULL DEFAULT 'unknown',
            tags            TEXT NOT NULL DEFAULT '[]',
            first_seen      TEXT NOT NULL,
            last_seen       TEXT NOT NULL,
            total_checks    INTEGER NOT NULL DEFAULT 0,
            successful_checks INTEGER NOT NULL DEFAULT 0,
            avg_response_time_ms REAL NOT NULL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS health_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name      TEXT NOT NULL,
            status          TEXT NOT NULL,
            response_time_ms REAL NOT NULL,
            status_code     INTEGER,
            error           TEXT,
            timestamp       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cost_records (
            agent_name      TEXT NOT NULL,
            month           TEXT NOT NULL,
            estimated_tokens_in    INTEGER NOT NULL DEFAULT 0,
            estimated_tokens_out   INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd     REAL NOT NULL DEFAULT 0.0,
            last_updated    TEXT NOT NULL,
            PRIMARY KEY (agent_name, month)
        );

        CREATE TABLE IF NOT EXISTS alert_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name      TEXT NOT NULL,
            alert_type      TEXT NOT NULL,
            status          TEXT NOT NULL,
            message         TEXT,
            timestamp       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS config_baselines (
            agent_name      TEXT PRIMARY KEY,
            provider        TEXT NOT NULL,
            health_check_path TEXT NOT NULL DEFAULT '/health',
            expected_version TEXT,
            expected_tags   TEXT NOT NULL DEFAULT '[]',
            additional_fields TEXT NOT NULL DEFAULT '{}',
            captured_at     TEXT NOT NULL,
            captured_by     TEXT NOT NULL DEFAULT 'manual'
        );

        CREATE TABLE IF NOT EXISTS drift_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name      TEXT NOT NULL,
            field           TEXT NOT NULL,
            expected        TEXT NOT NULL,
            actual          TEXT NOT NULL,
            severity        TEXT NOT NULL DEFAULT 'medium',
            message         TEXT,
            detected_at     TEXT NOT NULL
        );
    """)
    conn.commit()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a database connection with tables ensured."""
    from agent_control_plane.config import get_db_path

    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


def upsert_agent(conn: sqlite3.Connection, agent: AgentRecord) -> None:
    """Insert or update an agent record."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO agents (name, url, provider, status, tags, first_seen, last_seen,
                            total_checks, successful_checks, avg_response_time_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            url               = excluded.url,
            provider          = excluded.provider,
            status            = excluded.status,
            tags              = excluded.tags,
            last_seen         = excluded.last_seen,
            total_checks      = excluded.total_checks,
            successful_checks = excluded.successful_checks,
            avg_response_time_ms = excluded.avg_response_time_ms
        """,
        (
            agent.name,
            agent.url,
            agent.provider,
            agent.status.value,
            json.dumps(agent.tags),
            agent.first_seen.isoformat(),
            agent.last_seen.isoformat(),
            agent.total_checks,
            agent.successful_checks,
            agent.avg_response_time_ms,
        ),
    )
    conn.commit()


def get_agent(conn: sqlite3.Connection, name: str) -> AgentRecord | None:
    """Get a single agent by name."""
    row = conn.execute(
        "SELECT * FROM agents WHERE name = ?", (name,),
    ).fetchone()
    return _row_to_agent(row) if row else None


def list_agents(conn: sqlite3.Connection) -> list[AgentRecord]:
    """List all agents in the inventory."""
    rows = conn.execute("SELECT * FROM agents ORDER BY name").fetchall()
    return [_row_to_agent(r) for r in rows]


def delete_agent(conn: sqlite3.Connection, name: str) -> None:
    """Delete an agent and its health logs."""
    conn.execute("DELETE FROM agents WHERE name = ?", (name,))
    conn.execute("DELETE FROM health_log WHERE agent_name = ?", (name,))
    conn.execute("DELETE FROM cost_records WHERE agent_name = ?", (name,))
    conn.commit()


def _row_to_agent(row: sqlite3.Row) -> AgentRecord:
    return AgentRecord(
        name=row["name"],
        url=row["url"],
        provider=row["provider"],
        status=AgentStatus(row["status"]),
        tags=json.loads(row["tags"]),
        first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]),
        total_checks=row["total_checks"],
        successful_checks=row["successful_checks"],
        avg_response_time_ms=row["avg_response_time_ms"],
    )


# ---------------------------------------------------------------------------
# Health log
# ---------------------------------------------------------------------------


def log_health_check(
    conn: sqlite3.Connection,
    agent_name: str,
    status: AgentStatus,
    response_time_ms: float,
    status_code: int | None = None,
    error: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    """Record a health check result."""
    ts = (timestamp or datetime.now(UTC)).isoformat()
    conn.execute(
        """
        INSERT INTO health_log (agent_name, status, response_time_ms, status_code, error, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (agent_name, status.value, response_time_ms, status_code, error, ts),
    )
    conn.commit()


def get_health_history(
    conn: sqlite3.Connection, agent_name: str, limit: int = 100,
) -> list[dict[str, Any]]:
    """Get health check history for an agent."""
    rows = conn.execute(
        "SELECT * FROM health_log WHERE agent_name = ? ORDER BY timestamp DESC LIMIT ?",
        (agent_name, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Cost records
# ---------------------------------------------------------------------------


def upsert_cost_record(conn: sqlite3.Connection, record: CostRecord) -> None:
    """Insert or update a cost record."""
    conn.execute(
        """
        INSERT INTO cost_records (agent_name, month, estimated_tokens_in, estimated_tokens_out,
                                   estimated_cost_usd, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(agent_name, month) DO UPDATE SET
            estimated_tokens_in  = excluded.estimated_tokens_in,
            estimated_tokens_out = excluded.estimated_tokens_out,
            estimated_cost_usd   = excluded.estimated_cost_usd,
            last_updated         = excluded.last_updated
        """,
        (
            record.agent_name,
            record.month,
            record.estimated_tokens_in,
            record.estimated_tokens_out,
            record.estimated_cost_usd,
            record.last_updated.isoformat(),
        ),
    )
    conn.commit()


def list_cost_records(conn: sqlite3.Connection) -> list[CostRecord]:
    """List all cost records."""
    rows = conn.execute(
        "SELECT * FROM cost_records ORDER BY month DESC, agent_name",
    ).fetchall()
    return [
        CostRecord(
            agent_name=r["agent_name"],
            month=r["month"],
            estimated_tokens_in=r["estimated_tokens_in"],
            estimated_tokens_out=r["estimated_tokens_out"],
            estimated_cost_usd=r["estimated_cost_usd"],
            last_updated=datetime.fromisoformat(r["last_updated"]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def get_summary_stats(conn: sqlite3.Connection) -> SummaryStats:
    """Get aggregate statistics about the agent fleet."""
    agents = list_agents(conn)
    cost_records = list_cost_records(conn)
    total_cost = sum(r.estimated_cost_usd for r in cost_records)

    return SummaryStats(
        total_agents=len(agents),
        online=sum(1 for a in agents if a.status == AgentStatus.ONLINE),
        offline=sum(1 for a in agents if a.status == AgentStatus.OFFLINE),
        degraded=sum(1 for a in agents if a.status == AgentStatus.DEGRADED),
        unknown=sum(1 for a in agents if a.status == AgentStatus.UNKNOWN),
        total_estimated_cost_monthly_usd=total_cost,
        total_checks_run=sum(a.total_checks for a in agents),
    )


# ---------------------------------------------------------------------------
# Config Baselines CRUD
# ---------------------------------------------------------------------------


def upsert_config_baseline(conn: sqlite3.Connection, baseline: ConfigBaseline) -> None:
    """Insert or update a config baseline for an agent."""
    conn.execute(
        """INSERT INTO config_baselines (agent_name, provider, health_check_path,
           expected_version, expected_tags, additional_fields, captured_at, captured_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(agent_name) DO UPDATE SET
               provider           = excluded.provider,
               health_check_path  = excluded.health_check_path,
               expected_version   = excluded.expected_version,
               expected_tags      = excluded.expected_tags,
               additional_fields  = excluded.additional_fields,
               captured_at        = excluded.captured_at,
               captured_by        = excluded.captured_by""",
        (
            baseline.agent_name,
            baseline.provider,
            baseline.health_check_path,
            baseline.expected_version,
            json.dumps(baseline.expected_tags),
            json.dumps(baseline.additional_fields),
            baseline.captured_at.isoformat(),
            baseline.captured_by,
        ),
    )
    conn.commit()


def get_config_baseline(conn: sqlite3.Connection, agent_name: str) -> ConfigBaseline | None:
    """Get the config baseline for an agent."""
    row = conn.execute(
        "SELECT * FROM config_baselines WHERE agent_name = ?", (agent_name,),
    ).fetchone()
    if row is None:
        return None
    return ConfigBaseline(
        agent_name=row["agent_name"],
        provider=row["provider"],
        health_check_path=row["health_check_path"],
        expected_version=row["expected_version"],
        expected_tags=json.loads(row["expected_tags"]),
        additional_fields=json.loads(row["additional_fields"]),
        captured_at=datetime.fromisoformat(row["captured_at"]),
        captured_by=row["captured_by"],
    )


def list_config_baselines(conn: sqlite3.Connection) -> list[ConfigBaseline]:
    """List all config baselines."""
    rows = conn.execute("SELECT * FROM config_baselines ORDER BY agent_name").fetchall()
    result: list[ConfigBaseline] = []
    for r in rows:
        result.append(ConfigBaseline(
            agent_name=r["agent_name"],
            provider=r["provider"],
            health_check_path=r["health_check_path"],
            expected_version=r["expected_version"],
            expected_tags=json.loads(r["expected_tags"]),
            additional_fields=json.loads(r["additional_fields"]),
            captured_at=datetime.fromisoformat(r["captured_at"]),
            captured_by=r["captured_by"],
        ))
    return result


def delete_config_baseline(conn: sqlite3.Connection, agent_name: str) -> None:
    """Delete a config baseline for an agent."""
    conn.execute("DELETE FROM config_baselines WHERE agent_name = ?", (agent_name,))
    conn.commit()


# ---------------------------------------------------------------------------
# Drift Log CRUD
# ---------------------------------------------------------------------------


def log_drift(conn: sqlite3.Connection, drift: DriftRecord) -> None:
    """Record a drift detection event."""
    conn.execute(
        """INSERT INTO drift_log (agent_name, field, expected, actual, severity, message, detected_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (drift.agent_name, drift.field_name, drift.expected, drift.actual,
         drift.severity, drift.message, drift.detected_at.isoformat()),
    )
    conn.commit()


def get_drift_history(
    conn: sqlite3.Connection,
    agent_name: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DriftRecord]:
    """Query drift detection history with optional filters."""
    conditions: list[str] = []
    params: list[str | int] = []

    if agent_name:
        conditions.append("agent_name = ?")
        params.append(agent_name)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM drift_log{where} ORDER BY detected_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    return [
        DriftRecord(
            id=r["id"],
            agent_name=r["agent_name"],
            field_name=r["field"],
            expected=r["expected"],
            actual=r["actual"],
            severity=r["severity"],
            message=r["message"],
            detected_at=datetime.fromisoformat(r["detected_at"]),
        )
        for r in rows
    ]


def get_drift_summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Get summary counts of drift events by severity."""
    rows = conn.execute(
        "SELECT severity, COUNT(*) as cnt FROM drift_log GROUP BY severity",
    ).fetchall()
    summary: dict[str, int] = {}
    for r in rows:
        summary[r["severity"]] = r["cnt"]
    return summary
