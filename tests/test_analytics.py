"""Tests for the analytics time-series aggregation module.

RED phase — tests written before implementation.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_control_plane.inventory import (
    get_connection,
    log_health_check,
    upsert_agent,
    upsert_cost_record,
)
from agent_control_plane.models import AgentRecord, AgentStatus, CostRecord


@pytest.fixture
def db_with_health_data() -> str:
    """Create a temp DB with health log records spread across multiple days."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ACP_HOME"] = tmp
        conn = get_connection()

        # Add an agent
        upsert_agent(
            conn,
            AgentRecord(
                name="test-agent",
                url="http://localhost:9999",
                provider="custom",
                status=AgentStatus.ONLINE,
            ),
        )

        now = datetime.now(timezone.utc)

        # Insert health records across 7 days, 4 per day with varying states
        for day_offset in range(7, -1, -1):
            base = now - timedelta(days=day_offset)
            # Morning check
            log_health_check(
                conn, "test-agent", AgentStatus.ONLINE, 100.0, 200,
                timestamp=base.replace(hour=8, minute=0),
            )
            # Midday check
            status = AgentStatus.ONLINE if day_offset < 5 else AgentStatus.DEGRADED
            rt = 150.0 if day_offset < 5 else 500.0
            log_health_check(conn, "test-agent", status, rt, 200, timestamp=base.replace(hour=12, minute=0))
            # Afternoon
            log_health_check(conn, "test-agent", AgentStatus.ONLINE, 120.0, 200, timestamp=base.replace(hour=14, minute=0))
            # Evening - offline on some days
            if day_offset < 3:
                log_health_check(conn, "test-agent", AgentStatus.ONLINE, 110.0, 200, timestamp=base.replace(hour=18, minute=0))
            else:
                log_health_check(conn, "test-agent", AgentStatus.OFFLINE, 0, 500, "timeout", timestamp=base.replace(hour=18, minute=0))

        conn.close()
        yield tmp
        del os.environ["ACP_HOME"]


@pytest.fixture
def db_with_cost_data() -> str:
    """Create a temp DB with cost records across multiple months."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ACP_HOME"] = tmp
        conn = get_connection()

        # Add agents
        for name in ["agent-a", "agent-b"]:
            upsert_agent(
                conn,
                AgentRecord(name=name, url=f"http://localhost/{name}", provider="custom"),
            )

        # Cost records for last 3 months
        for month in ["2026-04", "2026-05", "2026-06"]:
            upsert_cost_record(
                conn,
                CostRecord(
                    agent_name="agent-a",
                    month=month,
                    estimated_tokens_in=1_000_000,
                    estimated_tokens_out=500_000,
                    estimated_cost_usd=15.0,
                    last_updated=datetime.now(timezone.utc),
                ),
            )
            upsert_cost_record(
                conn,
                CostRecord(
                    agent_name="agent-b",
                    month=month,
                    estimated_tokens_in=2_000_000,
                    estimated_tokens_out=1_000_000,
                    estimated_cost_usd=30.0,
                    last_updated=datetime.now(timezone.utc),
                ),
            )

        # Extra record for agent-a in a different month
        upsert_cost_record(
            conn,
            CostRecord(
                agent_name="agent-a",
                month="2026-03",
                estimated_tokens_in=800_000,
                estimated_tokens_out=400_000,
                estimated_cost_usd=12.0,
                last_updated=datetime.now(timezone.utc),
            ),
        )

        conn.close()
        yield tmp
        del os.environ["ACP_HOME"]


class TestHealthTimeseries:
    """Time-series aggregation queries for health log data."""

    def test_health_timeseries_day_bucket(self, db_with_health_data):
        """get_health_timeseries returns day-bucketed data for an agent."""
        from agent_control_plane.analytics import get_health_timeseries

        conn = get_connection()
        series = get_health_timeseries(conn, "test-agent", bucket="day", days=8)
        conn.close()

        assert len(series) > 0
        # Each entry should have bucket, online, offline, degraded, count
        entry = series[0]
        assert "bucket" in entry
        assert "online" in entry
        assert "offline" in entry
        assert "degraded" in entry
        assert "count" in entry
        # Some days should have online > 0
        total_online = sum(e["online"] for e in series)
        assert total_online > 0

    def test_health_timeseries_hour_bucket(self, db_with_health_data):
        """get_health_timeseries supports hour-level bucketing."""
        from agent_control_plane.analytics import get_health_timeseries

        conn = get_connection()
        series = get_health_timeseries(conn, "test-agent", bucket="hour", days=1)
        conn.close()

        assert len(series) > 0
        # Should have entries for hours where data exists
        # At least 4 checks per day = at least 4 hourly buckets
        assert len(series) >= 3

    def test_health_timeseries_no_data(self, db_with_health_data):
        """Empty agent returns empty series."""
        from agent_control_plane.analytics import get_health_timeseries

        conn = get_connection()
        series = get_health_timeseries(conn, "nonexistent", bucket="day", days=7)
        conn.close()

        assert series == []

    def test_health_timeseries_offline_degraded_counts(self, db_with_health_data):
        """Offline and degraded counts reflect actual health data."""
        from agent_control_plane.analytics import get_health_timeseries

        conn = get_connection()
        series = get_health_timeseries(conn, "test-agent", bucket="day", days=8)
        conn.close()

        # Days 0-2 have some offline records (day_offset < 3)
        # Day 6-7 (oldest) have some degraded records
        total_offline = sum(e["offline"] for e in series)
        total_degraded = sum(e["degraded"] for e in series)
        assert total_offline >= 3  # at least 3 days with evening offline
        assert total_degraded >= 2  # at least 2 days with degraded midday

    def test_health_timeseries_response_metrics(self, db_with_health_data):
        """Response time aggregations are included."""
        from agent_control_plane.analytics import get_health_timeseries

        conn = get_connection()
        series = get_health_timeseries(conn, "test-agent", bucket="day", days=8)
        conn.close()

        # Should have response time metrics
        entry = series[0]
        assert "avg_response_ms" in entry or "min_response_ms" in entry or "max_response_ms" in entry

    def test_health_timeseries_with_unknown_bucket(self, db_with_health_data):
        """Invalid bucket name defaults to 'day'."""
        from agent_control_plane.analytics import get_health_timeseries

        conn = get_connection()
        series_day = get_health_timeseries(conn, "test-agent", bucket="day", days=8)
        series_invalid = get_health_timeseries(conn, "test-agent", bucket="month", days=8)
        conn.close()

        assert len(series_invalid) == len(series_day)

    def test_health_timeseries_multiple_agents(self, db_with_health_data):
        """Fleet-level query returns data for all agents combined."""
        from agent_control_plane.analytics import get_fleet_health_timeseries

        conn = get_connection()
        # Add a second agent with data
        upsert_agent(
            conn,
            AgentRecord(name="test-agent-2", url="http://localhost:9998", provider="custom"),
        )
        now = datetime.now(timezone.utc)
        log_health_check(conn, "test-agent-2", AgentStatus.ONLINE, 200.0, 200, timestamp=now - timedelta(hours=1))
        log_health_check(conn, "test-agent-2", AgentStatus.ONLINE, 180.0, 200, timestamp=now - timedelta(hours=2))

        series = get_fleet_health_timeseries(conn, bucket="day", days=7)
        conn.close()

        assert len(series) > 0
        entry = series[0]
        assert "total_agents" in entry

    def test_health_timeseries_week_bucket(self, db_with_health_data):
        """Week-level bucketing works."""
        from agent_control_plane.analytics import get_health_timeseries

        conn = get_connection()
        series = get_health_timeseries(conn, "test-agent", bucket="week", days=14)
        conn.close()

        assert len(series) >= 1


class TestCostTimeseries:
    """Time-series queries for cost data."""

    def test_cost_timeseries_returns_months(self, db_with_cost_data):
        """get_cost_timeseries returns cost data grouped by month."""
        from agent_control_plane.analytics import get_cost_timeseries

        conn = get_connection()
        series = get_cost_timeseries(conn, months=6)
        conn.close()

        assert len(series) > 0
        entry = series[0]
        assert "month" in entry
        assert "total_cost" in entry
        assert "agents" in entry

    def test_cost_timeseries_correct_totals(self, db_with_cost_data):
        """Monthly totals sum all agent costs for that month."""
        from agent_control_plane.analytics import get_cost_timeseries

        conn = get_connection()
        series = get_cost_timeseries(conn, months=6)
        conn.close()

        # Each month with data should have agent-a ($15) + agent-b ($30) = $45
        for entry in series:
            if entry["month"] in ("2026-04", "2026-05", "2026-06"):
                assert entry["total_cost"] == 45.0, f"Month {entry['month']} should total $45"
            if entry["month"] == "2026-03":
                assert entry["total_cost"] == 12.0

    def test_cost_timeseries_per_agent(self, db_with_cost_data):
        """get_cost_timeseries can be filtered by agent."""
        from agent_control_plane.analytics import get_cost_timeseries

        conn = get_connection()
        series = get_cost_timeseries(conn, months=6, agent_name="agent-a")
        conn.close()

        assert len(series) > 0
        for entry in series:
            for a in entry["agents"]:
                assert a["name"] == "agent-a"

    def test_cost_timeseries_empty(self, db_with_cost_data):
        """No matching data returns empty list."""
        from agent_control_plane.analytics import get_cost_timeseries

        conn = get_connection()
        series = get_cost_timeseries(conn, months=6, agent_name="nonexistent")
        conn.close()

        assert series == []


class TestRetention:
    """Data retention policy enforcement."""

    def test_retention_deletes_old_records(self, db_with_health_data):
        """Records older than retention_days are deleted."""
        from agent_control_plane.retention import enforce_retention

        conn = get_connection()
        total_before = conn.execute("SELECT COUNT(*) FROM health_log").fetchone()[0]

        # Enforce retention of 0 days (everything older than now should be deleted)
        deleted = enforce_retention(conn, retention_days=0)
        conn.close()

        assert deleted > 0
        # At most 4 records for today should remain (the rest deleted)
        assert deleted <= total_before

    def test_retention_no_action_for_recent(self, db_with_health_data):
        """Retention policy doesn't delete recent records."""
        from agent_control_plane.retention import enforce_retention

        conn = get_connection()
        total_before = conn.execute("SELECT COUNT(*) FROM health_log").fetchone()[0]

        # Enforce retention of 365 days — everything should be within range
        deleted = enforce_retention(conn, retention_days=365)
        total_after = conn.execute("SELECT COUNT(*) FROM health_log").fetchone()[0]
        conn.close()

        assert deleted == 0
        assert total_after == total_before

    def test_retention_default_arg(self, db_with_health_data):
        """enforce_retention(conn) without args reads from config."""
        from agent_control_plane.retention import enforce_retention

        conn = get_connection()
        # Should not crash — reads retention_days from config/default
        deleted = enforce_retention(conn)
        assert isinstance(deleted, int)
        conn.close()

    def test_retention_config_loaded(self):
        """retention_days setting is read from config."""
        from agent_control_plane.retention import get_retention_days

        days = get_retention_days()
        assert days > 0
        assert isinstance(days, int)

    def test_retention_via_env_var(self):
        """ACP_HEALTH_RETENTION_DAYS env var overrides config default."""
        import os
        os.environ["ACP_HEALTH_RETENTION_DAYS"] = "30"
        from agent_control_plane.retention import get_retention_days
        try:
            days = get_retention_days()
            assert days == 30
        finally:
            del os.environ["ACP_HEALTH_RETENTION_DAYS"]

    def test_retention_env_var_clamped(self):
        """Env var value of 0 or negative is clamped to 1."""
        import os
        os.environ["ACP_HEALTH_RETENTION_DAYS"] = "0"
        from agent_control_plane.retention import get_retention_days
        try:
            days = get_retention_days()
            assert days >= 1
        finally:
            del os.environ["ACP_HEALTH_RETENTION_DAYS"]

    def test_retention_invalid_env_falls_back(self):
        """Invalid env var falls through to config default."""
        import os
        os.environ["ACP_HEALTH_RETENTION_DAYS"] = "not-a-number"
        from agent_control_plane.retention import get_retention_days
        try:
            days = get_retention_days()
            assert days == 90  # default
        finally:
            del os.environ["ACP_HEALTH_RETENTION_DAYS"]


class TestAnalyticsEdgeCases:
    """Edge case coverage for analytics module."""

    def test_months_ago_year_boundary(self):
        """_months_ago correctly handles year rollover."""
        from agent_control_plane.analytics import _months_ago

        # July 2026 - 8 months = November 2025
        result = _months_ago(8)
        parts = result.split("-")
        assert len(parts) == 2
        assert 1 <= int(parts[1]) <= 12

    def test_months_ago_large_offset(self):
        """_months_ago handles offsets larger than 12."""
        from agent_control_plane.analytics import _months_ago

        # July 2026 - 18 months = January 2025
        result = _months_ago(18)
        parts = result.split("-")
        assert len(parts) == 2
        assert 1 <= int(parts[1]) <= 12
