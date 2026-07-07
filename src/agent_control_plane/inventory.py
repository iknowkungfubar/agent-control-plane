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
    ShadowService,
    SummaryStats,
    Team,
    TeamMember,
    User,
    UserRole,
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

        CREATE TABLE IF NOT EXISTS users (
            name            TEXT PRIMARY KEY,
            email           TEXT NOT NULL,
            role            TEXT NOT NULL DEFAULT 'viewer',
            api_key_hash    TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL,
            last_seen       TEXT
        );

        CREATE TABLE IF NOT EXISTS teams (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_members (
            user_name       TEXT NOT NULL,
            team_id         TEXT NOT NULL,
            role_in_team    TEXT NOT NULL DEFAULT 'viewer',
            PRIMARY KEY (user_name, team_id),
            FOREIGN KEY (user_name) REFERENCES users(name) ON DELETE CASCADE,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
        );
    """)
    conn.commit()

    # Migrate existing databases: add team_id column to agents if missing
    try:
        conn.execute("ALTER TABLE agents ADD COLUMN team_id TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migrate: add notification_history table
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notification_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                channel         TEXT NOT NULL,
                alert_type      TEXT NOT NULL,
                agent_name      TEXT NOT NULL,
                status          TEXT,
                message         TEXT,
                success         INTEGER NOT NULL DEFAULT 0,
                error           TEXT,
                sent_at         TEXT NOT NULL
            );
        """)
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migrate: add shadow_catalog table
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS shadow_catalog (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                url             TEXT NOT NULL,
                service_type    TEXT NOT NULL DEFAULT 'unknown',
                risk            TEXT NOT NULL DEFAULT 'unknown',
                host            TEXT NOT NULL DEFAULT '',
                port            INTEGER NOT NULL DEFAULT 0,
                discovered_by   TEXT NOT NULL DEFAULT 'port_scan',
                first_seen      TEXT NOT NULL,
                last_seen       TEXT NOT NULL,
                tags            TEXT NOT NULL DEFAULT '[]',
                metadata        TEXT NOT NULL DEFAULT '{}'
            );
        """)
        conn.commit()
    except sqlite3.OperationalError:
        pass


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


def get_user_team_ids(conn: sqlite3.Connection, user_name: str) -> list[str]:
    """Get team IDs a user belongs to (admin users see all)."""
    user = get_user(conn, user_name)
    if user is None or user.role == UserRole.ADMIN:
        return []  # Empty means no filter (admin sees all)
    rows = conn.execute(
        "SELECT team_id FROM team_members WHERE user_name = ?", (user_name,)
    ).fetchall()
    return [r["team_id"] for r in rows]


def list_agents(
    conn: sqlite3.Connection,
    team_ids: list[str] | None = None,
) -> list[AgentRecord]:
    """List agents, optionally filtered by team IDs.

    Args:
        conn: Database connection.
        team_ids: If provided, only agents in these teams are returned.
                  If empty list or None, all agents are returned.
    """
    if team_ids is not None:
        if not team_ids:
            return []  # Empty team list means no agents visible
        placeholders = ",".join("?" for _ in team_ids)
        rows = conn.execute(
            f"SELECT * FROM agents WHERE team_id IN ({placeholders}) ORDER BY name",
            team_ids,
        ).fetchall()
    else:
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
        team_id=row["team_id"] if row["team_id"] else None,
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
        "SELECT severity, COUNT(*) as cnt FROM drift_log GROUP BY severity"
    ).fetchall()
    summary: dict[str, int] = {}
    for r in rows:
        summary[r["severity"]] = r["cnt"]
    return summary


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------


def upsert_user(conn: sqlite3.Connection, user: User) -> None:
    """Insert or update a user."""
    conn.execute(
        """INSERT INTO users (name, email, role, api_key_hash, created_at, last_seen)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
               email        = excluded.email,
               role         = excluded.role,
               api_key_hash = excluded.api_key_hash,
               last_seen    = excluded.last_seen""",
        (user.name, user.email, user.role.value, user.api_key_hash,
         user.created_at.isoformat(),
         user.last_seen.isoformat() if user.last_seen else None),
    )
    conn.commit()


def get_user(conn: sqlite3.Connection, name: str) -> User | None:
    """Get a user by name."""
    row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_email(conn: sqlite3.Connection, email: str) -> User | None:
    """Get a user by email."""
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return _row_to_user(row) if row else None


def list_users(conn: sqlite3.Connection) -> list[User]:
    """List all users."""
    rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    return [_row_to_user(r) for r in rows]


def delete_user(conn: sqlite3.Connection, name: str) -> None:
    """Delete a user and their team memberships."""
    conn.execute("DELETE FROM team_members WHERE user_name = ?", (name,))
    conn.execute("DELETE FROM users WHERE name = ?", (name,))
    conn.commit()


def check_single_user_mode(conn: sqlite3.Connection) -> bool:
    """Return True if no users exist (single-user mode)."""
    count = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    return count["cnt"] == 0


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        name=row["name"],
        email=row["email"],
        role=UserRole(row["role"]),
        api_key_hash=row["api_key_hash"] if row["api_key_hash"] else "",
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else None,
    )


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------


def upsert_team(conn: sqlite3.Connection, team: Team) -> None:
    """Insert or update a team."""
    conn.execute(
        """INSERT INTO teams (id, name, description, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name        = excluded.name,
               description = excluded.description""",
        (team.id, team.name, team.description, team.created_at.isoformat()),
    )
    conn.commit()


def get_team(conn: sqlite3.Connection, team_id: str) -> Team | None:
    """Get a team by ID."""
    row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
    return Team(id=row["id"], name=row["name"], description=row["description"],
                created_at=datetime.fromisoformat(row["created_at"])) if row else None


def list_teams(conn: sqlite3.Connection) -> list[Team]:
    """List all teams."""
    rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    return [
        Team(id=r["id"], name=r["name"], description=r["description"],
             created_at=datetime.fromisoformat(r["created_at"]))
        for r in rows
    ]


def delete_team(conn: sqlite3.Connection, team_id: str) -> None:
    """Delete a team and its memberships and unassign its agents."""
    conn.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
    conn.execute("UPDATE agents SET team_id = NULL WHERE team_id = ?", (team_id,))
    conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Team Member CRUD
# ---------------------------------------------------------------------------


def add_team_member(conn: sqlite3.Connection, member: TeamMember) -> None:
    """Add a user to a team with a role."""
    conn.execute(
        """INSERT OR REPLACE INTO team_members (user_name, team_id, role_in_team)
           VALUES (?, ?, ?)""",
        (member.user_name, member.team_id, member.role_in_team.value),
    )
    conn.commit()


def remove_team_member(conn: sqlite3.Connection, user_name: str, team_id: str) -> None:
    """Remove a user from a team."""
    conn.execute(
        "DELETE FROM team_members WHERE user_name = ? AND team_id = ?",
        (user_name, team_id),
    )
    conn.commit()


def list_team_members(conn: sqlite3.Connection, team_id: str) -> list[TeamMember]:
    """List all members of a team."""
    rows = conn.execute(
        "SELECT * FROM team_members WHERE team_id = ? ORDER BY user_name", (team_id,)
    ).fetchall()
    return [
        TeamMember(user_name=r["user_name"], team_id=r["team_id"],
                   role_in_team=UserRole(r["role_in_team"]))
        for r in rows
    ]


def get_user_teams(conn: sqlite3.Connection, user_name: str) -> list[Team]:
    """Get all teams a user belongs to."""
    rows = conn.execute(
        """SELECT t.* FROM teams t
           JOIN team_members tm ON t.id = tm.team_id
           WHERE tm.user_name = ?
           ORDER BY t.name""",
        (user_name,),
    ).fetchall()
    return [
        Team(id=r["id"], name=r["name"], description=r["description"],
             created_at=datetime.fromisoformat(r["created_at"]))
        for r in rows
    ]


def assign_agent_to_team(conn: sqlite3.Connection, agent_name: str, team_id: str) -> None:
    """Assign an agent to a team."""
    conn.execute(
        "UPDATE agents SET team_id = ? WHERE name = ?", (team_id, agent_name),
    )
    conn.commit()


def unassign_agent_from_team(conn: sqlite3.Connection, agent_name: str) -> None:
    """Remove an agent from its team assignment."""
    conn.execute(
        "UPDATE agents SET team_id = NULL WHERE name = ?", (agent_name,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Shadow Catalog CRUD
# ---------------------------------------------------------------------------


def upsert_shadow_service(conn: sqlite3.Connection, svc: ShadowService) -> int:
    """Insert or update a shadow service entry.

    Returns the ID of the record.
    """
    existing = conn.execute(
        "SELECT id FROM shadow_catalog WHERE url = ? AND service_type = ?",
        (svc.url, svc.service_type),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE shadow_catalog SET
               name=?, risk=?, last_seen=?, tags=?, metadata=?
               WHERE id=?""",
            (svc.name, svc.risk, svc.last_seen.isoformat(),
             json.dumps(svc.tags), json.dumps(svc.metadata), existing["id"]),
        )
        conn.commit()
        return existing["id"]
    else:
        cursor = conn.execute(
            """INSERT INTO shadow_catalog
               (name, url, service_type, risk, host, port, discovered_by,
                first_seen, last_seen, tags, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (svc.name, svc.url, svc.service_type, svc.risk,
             svc.host, svc.port, svc.discovered_by,
             svc.first_seen.isoformat(), svc.last_seen.isoformat(),
             json.dumps(svc.tags), json.dumps(svc.metadata)),
        )
        conn.commit()
        return cursor.lastrowid


def list_shadow_services(
    conn: sqlite3.Connection,
    risk: str | None = None,
    service_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ShadowService]:
    """List shadow IT services with optional filters."""
    conditions: list[str] = []
    params: list[str | int] = []

    if risk:
        conditions.append("risk = ?")
        params.append(risk)
    if service_type:
        conditions.append("service_type = ?")
        params.append(service_type)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM shadow_catalog{where} ORDER BY last_seen DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    return [_row_to_shadow(r) for r in rows]


def get_shadow_service(conn: sqlite3.Connection, service_id: int) -> ShadowService | None:
    """Get a single shadow service by ID."""
    row = conn.execute(
        "SELECT * FROM shadow_catalog WHERE id = ?", (service_id,)
    ).fetchone()
    return _row_to_shadow(row) if row else None


def delete_shadow_service(conn: sqlite3.Connection, service_id: int) -> None:
    """Delete a shadow service entry."""
    conn.execute("DELETE FROM shadow_catalog WHERE id = ?", (service_id,))
    conn.commit()


def get_shadow_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Get shadow IT summary counts by risk level and type."""
    by_risk: dict[str, int] = {}
    rows = conn.execute(
        "SELECT risk, COUNT(*) as cnt FROM shadow_catalog GROUP BY risk"
    ).fetchall()
    for r in rows:
        by_risk[r["risk"]] = r["cnt"]

    by_type: dict[str, int] = {}
    rows = conn.execute(
        "SELECT service_type, COUNT(*) as cnt FROM shadow_catalog GROUP BY service_type"
    ).fetchall()
    for r in rows:
        by_type[r["service_type"]] = r["cnt"]

    return {"by_risk": by_risk, "by_type": by_type, "total": sum(by_risk.values())}


def _row_to_shadow(row: sqlite3.Row) -> ShadowService:
    return ShadowService(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        service_type=row["service_type"],
        risk=row["risk"],
        host=row["host"],
        port=row["port"],
        discovered_by=row["discovered_by"],
        first_seen=datetime.fromisoformat(row["first_seen"]),
        last_seen=datetime.fromisoformat(row["last_seen"]),
        tags=json.loads(row["tags"]),
        metadata=json.loads(row["metadata"]),
    )
