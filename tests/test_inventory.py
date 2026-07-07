"""Unit tests for inventory database module."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_control_plane.models import AgentRecord, AgentStatus, CostRecord


@pytest.fixture
def db_conn():
    """Create a temporary database connection."""
    from agent_control_plane.inventory import get_connection
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        conn = get_connection(db_path)
        yield conn
        conn.close()


class TestAgentCRUD:
    """Test agent CRUD operations."""

    def _make_agent(self, name: str = "test-agent", status: AgentStatus = AgentStatus.UNKNOWN) -> AgentRecord:
        return AgentRecord(
            name=name,
            url=f"http://localhost:8080/{name}",
            provider="custom",
            status=status,
            tags=["test"],
        )

    def test_upsert_and_get(self, db_conn):
        """Insert an agent and retrieve it."""
        agent = self._make_agent("test-1")
        from agent_control_plane.inventory import get_agent, upsert_agent
        upsert_agent(db_conn, agent)
        retrieved = get_agent(db_conn, "test-1")
        assert retrieved is not None
        assert retrieved.name == "test-1"
        assert retrieved.provider == "custom"
        assert "test" in retrieved.tags

    def test_upsert_updates_existing(self, db_conn):
        """Upsert updates an existing agent's fields."""
        from agent_control_plane.inventory import get_agent, upsert_agent
        agent = self._make_agent("updatable", status=AgentStatus.UNKNOWN)
        upsert_agent(db_conn, agent)

        agent.status = AgentStatus.ONLINE
        agent.provider = "openai"
        upsert_agent(db_conn, agent)

        updated = get_agent(db_conn, "updatable")
        assert updated is not None
        assert updated.status == AgentStatus.ONLINE
        assert updated.provider == "openai"

    def test_get_nonexistent(self, db_conn):
        """Getting a nonexistent agent returns None."""
        from agent_control_plane.inventory import get_agent
        assert get_agent(db_conn, "ghost") is None

    def test_list_agents(self, db_conn):
        """List returns all agents."""
        from agent_control_plane.inventory import list_agents, upsert_agent
        upsert_agent(db_conn, self._make_agent("a1"))
        upsert_agent(db_conn, self._make_agent("a2"))
        upsert_agent(db_conn, self._make_agent("a3"))
        agents = list_agents(db_conn)
        assert len(agents) == 3
        assert [a.name for a in agents] == ["a1", "a2", "a3"]

    def test_delete_agent(self, db_conn):
        """Delete removes agent and related records."""
        from agent_control_plane.inventory import delete_agent, get_agent, upsert_agent
        agent = self._make_agent("delete-me")
        upsert_agent(db_conn, agent)
        assert get_agent(db_conn, "delete-me") is not None
        delete_agent(db_conn, "delete-me")
        assert get_agent(db_conn, "delete-me") is None

    def test_agent_default_values(self):
        """AgentRecord gets correct defaults."""
        now = datetime.now(UTC)
        agent = AgentRecord(name="defaults-test", url="http://localhost:9999", provider="custom")
        assert agent.status == AgentStatus.UNKNOWN
        assert agent.tags == []
        assert agent.total_checks == 0
        assert agent.successful_checks == 0
        assert agent.avg_response_time_ms == 0.0


class TestHealthLog:
    """Test health log operations."""

    def test_log_health_check(self, db_conn):
        """Log a health check and verify it's stored."""
        from agent_control_plane.inventory import get_health_history, log_health_check, upsert_agent

        # First add the agent
        upsert_agent(db_conn, AgentRecord(name="hl-agent", url="http://localhost:1", provider="custom"))

        log_health_check(
            db_conn, agent_name="hl-agent", status=AgentStatus.ONLINE,
            response_time_ms=45.2, status_code=200,
        )
        history = get_health_history(db_conn, "hl-agent")
        assert len(history) >= 1
        assert history[0]["status"] == "online"
        assert history[0]["response_time_ms"] == 45.2

    def test_log_with_error(self, db_conn):
        """Health log stores error details."""
        from agent_control_plane.inventory import get_health_history, log_health_check, upsert_agent

        upsert_agent(db_conn, AgentRecord(name="err-agent", url="http://localhost:2", provider="custom"))
        log_health_check(
            db_conn, agent_name="err-agent", status=AgentStatus.OFFLINE,
            response_time_ms=0, status_code=None, error="connection refused",
        )
        history = get_health_history(db_conn, "err-agent")
        assert history[0]["error"] == "connection refused"
        assert history[0]["status"] == "offline"


class TestCostRecords:
    """Test cost record operations."""

    def test_upsert_cost_record(self, db_conn):
        """Insert and retrieve a cost record."""
        from agent_control_plane.inventory import list_cost_records, upsert_cost_record
        record = CostRecord(
            agent_name="cost-agent",
            month="2026-07",
            estimated_tokens_in=100000,
            estimated_tokens_out=50000,
            estimated_cost_usd=12.50,
        )
        upsert_cost_record(db_conn, record)
        records = list_cost_records(db_conn)
        assert len(records) == 1
        assert records[0].agent_name == "cost-agent"
        assert records[0].estimated_cost_usd == 12.50

    def test_upsert_updates_cost(self, db_conn):
        """Upsert updates existing cost record for same agent+month."""
        from agent_control_plane.inventory import list_cost_records, upsert_cost_record
        r1 = CostRecord(agent_name="ca", month="2026-07", estimated_cost_usd=5.0)
        r2 = CostRecord(agent_name="ca", month="2026-07", estimated_cost_usd=10.0)
        upsert_cost_record(db_conn, r1)
        upsert_cost_record(db_conn, r2)
        records = list_cost_records(db_conn)
        assert len(records) == 1
        assert records[0].estimated_cost_usd == 10.0


class TestSummaryStats:
    """Test summary statistics."""

    def test_empty_summary(self, db_conn):
        """Empty inventory gives zero stats."""
        from agent_control_plane.inventory import get_summary_stats
        stats = get_summary_stats(db_conn)
        assert stats.total_agents == 0
        assert stats.online == 0
        assert stats.total_estimated_cost_monthly_usd == 0.0
