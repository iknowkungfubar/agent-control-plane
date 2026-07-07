"""Tests for configuration drift detection."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_control_plane.models import (
    ConfigBaseline,
    DriftCheckResult,
    DriftRecord,
    DriftReport,
    DriftSeverity,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_config_baseline_defaults(self):
        """ConfigBaseline sets sensible defaults."""
        baseline = ConfigBaseline(agent_name="test-agent", provider="custom")
        assert baseline.agent_name == "test-agent"
        assert baseline.provider == "custom"
        assert baseline.health_check_path == "/health"
        assert baseline.expected_version is None
        assert baseline.expected_tags == []
        assert baseline.additional_fields == {}
        assert baseline.captured_by == "manual"

    def test_config_baseline_with_all_fields(self):
        """ConfigBaseline accepts all fields."""
        now = datetime.now(UTC)
        baseline = ConfigBaseline(
            agent_name="agent-1",
            provider="openai",
            health_check_path="/healthz",
            expected_version="gpt-4",
            expected_tags=["prod", "llm"],
            additional_fields={"env": "staging"},
            captured_at=now,
            captured_by="auto",
        )
        assert baseline.agent_name == "agent-1"
        assert baseline.expected_version == "gpt-4"
        assert "prod" in baseline.expected_tags
        assert baseline.additional_fields["env"] == "staging"
        assert baseline.captured_by == "auto"

    def test_drift_check_result_defaults(self):
        """DriftCheckResult sets checked_at."""
        result = DriftCheckResult(
            agent_name="agent-1",
            field="provider",
            expected="openai",
            actual="anthropic",
            severity="high",
            message="Provider changed",
        )
        assert result.agent_name == "agent-1"
        assert result.severity == "high"
        assert result.checked_at is not None

    def test_drift_severity_enum(self):
        """DriftSeverity has expected values."""
        assert DriftSeverity.NONE.value == "none"
        assert DriftSeverity.LOW.value == "low"
        assert DriftSeverity.MEDIUM.value == "medium"
        assert DriftSeverity.HIGH.value == "high"
        assert DriftSeverity.CRITICAL.value == "critical"

    def test_drift_record_defaults(self):
        """DriftRecord sets detected_at."""
        record = DriftRecord(
            agent_name="agent-1", field_name="provider",
            expected="a", actual="b",
            severity="high", message="Changed",
        )
        assert record.detected_at is not None
        assert record.id is None

    def test_drift_report_defaults(self):
        """DriftReport tracks drift count and severity."""
        results = [
            DriftCheckResult(
                agent_name="a", field="f1",
                expected="x", actual="y",
                severity="high", message="drift",
            ),
        ]
        report = DriftReport(
            agent_name="agent-1",
            has_baseline=True,
            drift_count=1,
            max_severity=DriftSeverity.HIGH,
            results=results,
        )
        assert report.drift_count == 1
        assert report.max_severity == DriftSeverity.HIGH
        assert len(report.results) == 1


# ---------------------------------------------------------------------------
# Inventory CRUD tests
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a temporary SQLite database with tables for testing."""
    from agent_control_plane.inventory import _ensure_tables
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


class TestBaselineCRUD:
    def test_upsert_and_get_baseline(self, conn):
        """Insert a baseline, then retrieve it."""
        from agent_control_plane.inventory import (
            get_config_baseline,
            upsert_config_baseline,
        )

        now = datetime.now(UTC)
        baseline = ConfigBaseline(
            agent_name="test-agent",
            provider="openai",
            health_check_path="/v1/health",
            expected_version="gpt-4",
            expected_tags=["prod"],
            additional_fields={"env": "production"},
            captured_at=now,
            captured_by="manual",
        )
        upsert_config_baseline(conn, baseline)

        retrieved = get_config_baseline(conn, "test-agent")
        assert retrieved is not None
        assert retrieved.agent_name == "test-agent"
        assert retrieved.provider == "openai"
        assert retrieved.expected_version == "gpt-4"
        assert retrieved.expected_tags == ["prod"]
        assert retrieved.additional_fields["env"] == "production"

    def test_upsert_baseline_updates_existing(self, conn):
        """Upserting same agent name updates the baseline."""
        from agent_control_plane.inventory import (
            get_config_baseline,
            upsert_config_baseline,
        )

        now = datetime.now(UTC)
        baseline1 = ConfigBaseline(
            agent_name="agent-x", provider="openai", captured_at=now,
        )
        upsert_config_baseline(conn, baseline1)

        baseline2 = ConfigBaseline(
            agent_name="agent-x", provider="anthropic",
            expected_version="claude-4", captured_at=now, captured_by="auto",
        )
        upsert_config_baseline(conn, baseline2)

        retrieved = get_config_baseline(conn, "agent-x")
        assert retrieved is not None
        assert retrieved.provider == "anthropic"
        assert retrieved.expected_version == "claude-4"
        assert retrieved.captured_by == "auto"

    def test_get_baseline_nonexistent(self, conn):
        """Getting baseline for nonexistent agent returns None."""
        from agent_control_plane.inventory import get_config_baseline
        result = get_config_baseline(conn, "no-such-agent")
        assert result is None

    def test_list_baselines(self, conn):
        """List all baselines."""
        from agent_control_plane.inventory import (
            list_config_baselines,
            upsert_config_baseline,
        )

        now = datetime.now(UTC)
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="agent-a", provider="openai", captured_at=now,
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="agent-b", provider="anthropic", captured_at=now,
        ))

        baselines = list_config_baselines(conn)
        assert len(baselines) == 2
        names = [b.agent_name for b in baselines]
        assert "agent-a" in names
        assert "agent-b" in names

    def test_delete_baseline(self, conn):
        """Delete a baseline by agent name."""
        from agent_control_plane.inventory import (
            delete_config_baseline,
            get_config_baseline,
            upsert_config_baseline,
        )

        now = datetime.now(UTC)
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="to-delete", provider="openai", captured_at=now,
        ))
        delete_config_baseline(conn, "to-delete")

        result = get_config_baseline(conn, "to-delete")
        assert result is None


class TestDriftLogCRUD:
    def test_log_and_query_drift(self, conn):
        """Log drift events and retrieve them."""
        from agent_control_plane.inventory import get_drift_history, log_drift

        now = datetime.now(UTC)
        log_drift(conn, DriftRecord(
            agent_name="agent-1", field_name="provider",
            expected="openai", actual="anthropic",
            severity="high", message="Provider changed",
            detected_at=now,
        ))
        log_drift(conn, DriftRecord(
            agent_name="agent-1", field_name="version",
            expected="1.0", actual="1.1",
            severity="low", message="Version changed",
            detected_at=now,
        ))

        records = get_drift_history(conn, agent_name="agent-1")
        assert len(records) == 2
        assert records[0].field_name in ("provider", "version")

    def test_get_drift_history_filtered(self, conn):
        """Filter drift history by severity."""
        from agent_control_plane.inventory import get_drift_history, log_drift

        now = datetime.now(UTC)
        log_drift(conn, DriftRecord(
            agent_name="a", field_name="p",
            expected="x", actual="y",
            severity="high", detected_at=now,
        ))
        log_drift(conn, DriftRecord(
            agent_name="a", field_name="v",
            expected="1", actual="2",
            severity="low", detected_at=now,
        ))

        high_records = get_drift_history(conn, severity="high")
        assert len(high_records) == 1
        assert high_records[0].severity == "high"

    def test_get_drift_summary(self, conn):
        """Get drift summary counts by severity."""
        from agent_control_plane.inventory import get_drift_summary, log_drift

        now = datetime.now(UTC)
        log_drift(conn, DriftRecord(
            agent_name="a", field_name="p",
            expected="x", actual="y",
            severity="high", detected_at=now,
        ))
        log_drift(conn, DriftRecord(
            agent_name="b", field_name="p",
            expected="x", actual="y",
            severity="high", detected_at=now,
        ))
        log_drift(conn, DriftRecord(
            agent_name="a", field_name="v",
            expected="1", actual="2",
            severity="low", detected_at=now,
        ))

        summary = get_drift_summary(conn)
        assert summary.get("high") == 2
        assert summary.get("low") == 1

    def test_drift_history_empty(self, conn):
        """Empty drift log returns empty list."""
        from agent_control_plane.inventory import get_drift_history
        records = get_drift_history(conn)
        assert records == []

    def test_drift_history_limit_and_offset(self, conn):
        """Test pagination of drift history."""
        from agent_control_plane.inventory import get_drift_history, log_drift

        now = datetime.now(UTC)
        for i in range(5):
            log_drift(conn, DriftRecord(
                agent_name="a", field_name=f"f{i}",
                expected="x", actual="y",
                severity="low", detected_at=now,
            ))

        limited = get_drift_history(conn, limit=2)
        assert len(limited) == 2


# ---------------------------------------------------------------------------
# Drift engine tests
# ---------------------------------------------------------------------------


class TestCompareField:
    """Test the _compare_field logic from the drift module."""

    def test_identical_values_no_drift(self):
        """Same expected and actual produces no drift."""
        from agent_control_plane.drift import _compare_field

        result = _compare_field("agent-1", "provider", "openai", "openai")
        assert DriftSeverity(result.severity) == DriftSeverity.NONE
        assert "'provider' matches baseline" in result.message

    def test_provider_change_high_severity(self):
        """Provider change is high severity."""
        from agent_control_plane.drift import _compare_field

        result = _compare_field("agent-1", "provider", "openai", "anthropic")
        assert DriftSeverity(result.severity) == DriftSeverity.HIGH
        assert "Provider changed" in result.message

    def test_version_change_low_severity(self):
        """Version change is low severity."""
        from agent_control_plane.drift import _compare_field

        result = _compare_field("agent-1", "version", "1.0", "1.1")
        assert DriftSeverity(result.severity) == DriftSeverity.LOW
        assert "Version changed" in result.message

    def test_health_path_change_medium_severity(self):
        """Health check path change is medium severity."""
        from agent_control_plane.drift import _compare_field

        result = _compare_field("agent-1", "health_check_path", "/health", "/healthz")
        assert DriftSeverity(result.severity) == DriftSeverity.MEDIUM

    def test_generic_change_medium_severity(self):
        """Generic field changes are medium severity."""
        from agent_control_plane.drift import _compare_field

        result = _compare_field("agent-1", "tags", "prod", "dev")
        assert DriftSeverity(result.severity) == DriftSeverity.MEDIUM


# ---------------------------------------------------------------------------
# Drift engine tests (continued)
# ---------------------------------------------------------------------------


class TestDriftEngine:
    """Test utility functions in drift engine."""

    def test_severity_rank_ordering(self):
        """Severity rank follows expected order."""
        from agent_control_plane.drift import _severity_rank

        assert _severity_rank(DriftSeverity.NONE) == 0
        assert _severity_rank(DriftSeverity.LOW) == 1
        assert _severity_rank(DriftSeverity.MEDIUM) == 2
        assert _severity_rank(DriftSeverity.HIGH) == 3
        assert _severity_rank(DriftSeverity.CRITICAL) == 4
        assert _severity_rank(DriftSeverity.NONE) < _severity_rank(DriftSeverity.LOW)
        assert _severity_rank(DriftSeverity.LOW) < _severity_rank(DriftSeverity.MEDIUM)
        assert _severity_rank(DriftSeverity.MEDIUM) < _severity_rank(DriftSeverity.HIGH)

    def test_probe_agent_config_unreachable(self):
        """Probing an unreachable host returns error."""
        from agent_control_plane.drift import _probe_agent_config

        config = _probe_agent_config("http://localhost:1", timeout=0.5)
        assert "error" in config
        assert config["has_v1_models"] is False

    def test_set_baseline_nonexistent_agent(self, conn):
        """Setting baseline for nonexistent agent returns None."""
        from agent_control_plane.drift import set_baseline

        result = set_baseline("no-such-agent", provider="openai")
        assert result is None

    def test_set_baseline_creates_record(self, conn):
        """Setting baseline creates a DB record."""
        from agent_control_plane.drift import set_baseline

        # Set up agent first
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO agents (name, url, provider, status, tags, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test-agent-1", "http://localhost:2", "openai", "unknown",
             '["prod"]', now, now),
        )
        conn.commit()

        baseline = set_baseline("test-agent-1", provider="anthropic", expected_version="claude-4", conn=conn)
        assert baseline is not None
        assert baseline.provider == "anthropic"

    def test_set_baseline_updates_existing(self, conn):
        """Setting baseline updates an existing one."""
        from agent_control_plane.drift import set_baseline
        from agent_control_plane.inventory import (
            upsert_config_baseline,
        )

        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO agents (name, url, provider, status, tags, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test-agent-2", "http://localhost:3", "openai", "unknown",
             "[]", now, now),
        )
        conn.commit()

        # Create initial baseline
        bl_now = datetime.now(UTC)
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="test-agent-2", provider="openai", captured_at=bl_now,
        ))

        # Update via set_baseline
        result = set_baseline("test-agent-2", provider="anthropic", conn=conn)
        assert result is not None
        assert result.provider == "anthropic"


class TestCheckDriftWithMock:
    """Test drift checking with mocked network calls."""

    def test_check_drift_provider_mismatch(self, monkeypatch, tmp_path):
        """Check drift detects provider mismatch."""
        import os

        os.environ["ACP_HOME"] = str(tmp_path)

        # Set up agent + baseline in DB
        from agent_control_plane.inventory import (
            get_connection,
            upsert_agent,
            upsert_config_baseline,
        )
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="drift-test-agent", url="http://localhost:9999",
            provider="anthropic", status=AgentStatus.ONLINE,
            tags=["prod"],
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="drift-test-agent", provider="openai",
            expected_version="gpt-4", captured_at=now,
        ))
        conn.close()

        from agent_control_plane.drift import check_drift

        report = check_drift("drift-test-agent", timeout=0.5)
        assert report.has_baseline
        assert report.drift_count >= 1
        # At minimum, provider should be different
        provider_drift = [r for r in report.results if r.field == "provider"]
        assert len(provider_drift) >= 1

    def test_check_drift_no_drift(self, monkeypatch, tmp_path):
        """Check drift passes when config matches."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import (
            get_connection,
            upsert_agent,
            upsert_config_baseline,
        )
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="drift-match-agent", url="http://localhost:9998",
            provider="openai", status=AgentStatus.ONLINE,
            tags=["prod"],
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="drift-match-agent", provider="openai",
            expected_tags=["prod"], captured_at=now,
        ))
        conn.close()

        from agent_control_plane.drift import check_drift

        report = check_drift("drift-match-agent", timeout=0.5)
        assert report.has_baseline
        # Provider should match (openai == openai)
        provider_drift = [r for r in report.results if r.field == "provider"]
        assert len(provider_drift) == 1
        assert provider_drift[0].severity == "none"


class TestDriftAlertDispatch:
    """Test the drift alert dispatch function."""

    def test_dispatch_drift_alert_disabled(self, tmp_path):
        """DRIFT alert is a no-op when run without config (alerts disabled)."""
        from agent_control_plane.alerts.engine import dispatch_drift_alert

        os.environ["ACP_HOME"] = str(tmp_path)
        dispatch_drift_alert("test-agent", drift_count=2, max_severity="high")
        # Should not raise


# ---------------------------------------------------------------------------
# E2E tests with real HTTP server
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def health_server():
    """Start a real HTTP server that returns health check JSON."""
    import http.server
    import threading
    import time

    class MockAgentHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "version": "gpt-4",
                    "service": "test-agent",
                    "environment": "test",
                }).encode())
            elif self.path == "/v1/models":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "data": [{"id": "gpt-4", "object": "model"}],
                }).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), MockAgentHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield port
    server.shutdown()


class TestDriftE2E:
    """End-to-end tests for drift detection with real HTTP."""

    def test_probe_agent_config_success(self, health_server):
        """_probe_agent_config returns health data from a real server."""
        from agent_control_plane.drift import _probe_agent_config

        config = _probe_agent_config(f"http://127.0.0.1:{health_server}", timeout=2.0)
        assert config["status_code"] == 200
        assert "response_body" in config
        assert config["response_body"]["status"] == "ok"
        assert config["response_body"]["version"] == "gpt-4"
        assert config["has_v1_models"] is True
        assert "model_ids" in config
        assert "gpt-4" in config["model_ids"]

    def test_probe_agent_config_404(self, health_server):
        """_probe_agent_config handles 404 responses."""
        from agent_control_plane.drift import _probe_agent_config

        config = _probe_agent_config(
            f"http://127.0.0.1:{health_server}",
            health_check_path="/nonexistent",
            timeout=2.0,
        )
        assert config["status_code"] == 404

    def test_capture_baseline_e2e(self, health_server, tmp_path):
        """Capture baseline from a real agent endpoint."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import get_connection, upsert_agent
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="e2e-agent",
            url=f"http://127.0.0.1:{health_server}",
            provider="openai",
            status=AgentStatus.ONLINE,
            tags=["e2e"],
        ))
        conn.close()

        from agent_control_plane.drift import capture_baseline

        baseline = capture_baseline("e2e-agent", timeout=2.0)
        assert baseline is not None
        assert baseline.provider == "openai"
        assert baseline.expected_version == "gpt-4"
        assert "environment" in baseline.additional_fields
        assert baseline.captured_by == "auto"

    def test_check_drift_e2e_matching(self, health_server, tmp_path):
        """Full drift check against a matching agent."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import (
            get_connection,
            upsert_agent,
            upsert_config_baseline,
        )
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="e2e-match",
            url=f"http://127.0.0.1:{health_server}",
            provider="openai",
            status=AgentStatus.ONLINE,
            tags=["e2e"],
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="e2e-match",
            provider="openai",
            expected_version="gpt-4",
            expected_tags=["e2e"],
            additional_fields={"environment": "test"},
            captured_at=now,
        ))
        conn.close()

        from agent_control_plane.drift import check_drift

        report = check_drift("e2e-match", timeout=2.0)
        assert report.has_baseline
        assert report.drift_count == 0
        assert report.max_severity == DriftSeverity.NONE

    def test_check_drift_e2e_mismatch(self, health_server, tmp_path):
        """Full drift check detects mismatched config."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import (
            get_connection,
            upsert_agent,
            upsert_config_baseline,
        )
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="e2e-mismatch",
            url=f"http://127.0.0.1:{health_server}",
            provider="anthropic",  # Different from baseline!
            status=AgentStatus.ONLINE,
            tags=["prod"],
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="e2e-mismatch",
            provider="openai",  # Baseline says openai
            expected_version="claude-4",  # But version says gpt-4
            additional_fields={"environment": "production"},  # Server says "test"
            captured_at=now,
        ))
        conn.close()

        from agent_control_plane.drift import check_drift

        report = check_drift("e2e-mismatch", timeout=2.0)
        assert report.has_baseline
        assert report.drift_count >= 1
        # Provider mismatch
        provider_drift = [r for r in report.results if r.field == "provider"]
        assert any(r.severity != "none" for r in provider_drift)

    def test_check_all_drift_e2e(self, health_server, tmp_path):
        """check_all_drift returns reports for agents with baselines."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import (
            get_connection,
            upsert_agent,
            upsert_config_baseline,
        )
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="all-drift-1", url=f"http://127.0.0.1:{health_server}",
            provider="openai", status=AgentStatus.ONLINE, tags=[],
        ))
        upsert_agent(conn, AgentRecord(
            name="all-drift-2", url=f"http://127.0.0.1:{health_server}",
            provider="openai", status=AgentStatus.ONLINE, tags=[],
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="all-drift-1", provider="openai",
            expected_version="gpt-4", captured_at=now,
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="all-drift-2", provider="openai",
            expected_version="gpt-4", captured_at=now,
        ))
        conn.close()

        from agent_control_plane.drift import check_all_drift

        reports = check_all_drift(timeout=2.0)
        assert len(reports) >= 2
        assert all(r.has_baseline for r in reports)

    def test_capture_baseline_already_exists(self, health_server, tmp_path):
        """capture_baseline updates existing baseline on re-capture."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import get_connection, upsert_agent
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="e2e-recapture", url=f"http://127.0.0.1:{health_server}",
            provider="openai", status=AgentStatus.ONLINE, tags=[],
        ))
        conn.close()

        from agent_control_plane.drift import capture_baseline

        # First capture
        first = capture_baseline("e2e-recapture", timeout=2.0)
        assert first is not None
        assert first.expected_version == "gpt-4"

        # Second capture (should update)
        second = capture_baseline("e2e-recapture", timeout=2.0)
        assert second is not None
        assert second.expected_version == "gpt-4"


class TestDriftAlertIntegration:
    """Integration tests for drift alerts."""

    def test_dispatch_drift_alert_with_config(self, tmp_path):
        """dispatch_drift_alert works when alerts are configured."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.alerts.engine import dispatch_drift_alert
        from agent_control_plane.inventory import (
            get_connection,
            get_drift_summary,
        )

        # Ensure DB directory exists
        (tmp_path / "inventory.db").parent.mkdir(parents=True, exist_ok=True)

        # Create a config file that enables alerts
        import yaml
        config = {"agents": [], "alerts": {"enabled": True, "global": {"consecutive_failures": 3, "rate_limit_seconds": 0}}}
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        os.environ["ACP_CONFIG"] = str(config_path)

        dispatch_drift_alert("integration-agent", drift_count=3, max_severity="critical",
                             details="Provider changed; Version changed")

        conn = get_connection()
        summary = get_drift_summary(conn)
        conn.close()
        assert "critical" not in summary  # No alert type "critical" in drift_log - DRIFT alerts go to alert_history table


# ---------------------------------------------------------------------------
# Dashboard API tests (via FastAPI TestClient)
# ---------------------------------------------------------------------------


@pytest.fixture
def test_app(tmp_path: Path):
    """Create a FastAPI test app with a test database."""
    os.environ["ACP_HOME"] = str(tmp_path)
    db_path = tmp_path / "inventory.db"

    # Set up tables and add test data
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    from agent_control_plane.inventory import _ensure_tables
    _ensure_tables(conn)

    # Insert test agent
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO agents (name, url, provider, status, tags, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("drift-agent", "http://localhost:9999", "openai", "online", '["test"]', now, now),
    )

    # Insert test baseline
    conn.execute(
        "INSERT INTO config_baselines (agent_name, provider, health_check_path, "
        "expected_version, expected_tags, additional_fields, captured_at, captured_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("drift-agent", "openai", "/health", "gpt-4", '["test"]', '{"env":"test"}', now, "auto"),
    )

    # Insert test drift events
    for sev in ("high", "low"):
        conn.execute(
            "INSERT INTO drift_log (agent_name, field, expected, actual, severity, message, detected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("drift-agent", "version", "gpt-4", "gpt-3.5", sev, f"{sev} severity drift", now),
        )

    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient

    from agent_control_plane.dashboard import create_app
    app = create_app()
    return TestClient(app)


class TestDriftDashboardAPI:
    def test_drift_summary_endpoint(self, test_app):
        """GET /api/drift/summary returns severity counts."""
        response = test_app.get("/api/drift/summary")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert data["summary"].get("high", 0) >= 1

    def test_drift_history_endpoint(self, test_app):
        """GET /api/drift returns drift events."""
        response = test_app.get("/api/drift")
        assert response.status_code == 200
        data = response.json()
        assert "drift_events" in data
        assert data["count"] >= 2

    def test_drift_agent_endpoint(self, test_app):
        """GET /api/drift/{agent_name} returns agent-specific drift."""
        response = test_app.get("/api/drift/drift-agent")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_name"] == "drift-agent"
        assert data["count"] >= 2

    def test_drift_agent_filter_by_severity(self, test_app):
        """GET /api/drift?severity=high filters by severity."""
        response = test_app.get("/api/drift?severity=high")
        assert response.status_code == 200
        data = response.json()
        for event in data["drift_events"]:
            assert event["severity"] == "high"

    def test_drift_nonexistent_agent(self, test_app):
        """GET /api/drift/nonexistent returns empty list."""
        response = test_app.get("/api/drift/no-such-agent")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0

    def test_drift_events_have_field_name(self, test_app):
        """Drift events include field_name in response."""
        response = test_app.get("/api/drift")
        data = response.json()
        if data["drift_events"]:
            assert "field_name" in data["drift_events"][0]

    def test_drift_summary_invalid_agent(self, test_app):
        """Drift summary for nonexistent agent returns empty."""
        response = test_app.get("/api/drift/summary")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data


class TestCLIDriftCommands:
    """Test CLI drift command structure."""

    def test_cli_has_drift_commands(self):
        """CLI parser recognizes drift commands."""
        from agent_control_plane.cli import _build_parser
        parser = _build_parser()

        # config-baseline
        args = parser.parse_args(["config-baseline", "list"])
        assert args.command == "config-baseline"
        assert args.config_baseline_command == "list"

        # drift-check
        args = parser.parse_args(["drift-check"])
        assert args.command == "drift-check"

        # drift-report
        args = parser.parse_args(["drift-report"])
        assert args.command == "drift-report"

        # config-baseline capture
        args = parser.parse_args(["config-baseline", "capture", "test-agent"])
        assert args.command == "config-baseline"
        assert args.config_baseline_command == "capture"
        assert args.name == "test-agent"

        # config-baseline set
        args = parser.parse_args(["config-baseline", "set", "test-agent", "--provider", "openai", "--version", "1.0"])
        assert args.config_baseline_command == "set"
        assert args.provider == "openai"
        assert args.version == "1.0"

    def test_cmd_drift_report_with_data(self, tmp_path):
        """CLI drift-report runs without error when data exists."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import get_connection, log_drift
        from agent_control_plane.models import DriftRecord

        conn = get_connection()
        now = datetime.now(UTC)
        log_drift(conn, DriftRecord(
            agent_name="cli-test-agent", field_name="provider",
            expected="openai", actual="anthropic",
            severity="high", message="Provider changed",
            detected_at=now,
        ))
        conn.close()

        from agent_control_plane.cli import cmd_drift_report
        cmd_drift_report()  # Should not raise

    def test_cmd_drift_report_empty(self, tmp_path):
        """CLI drift-report handles empty data gracefully."""
        import os
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.cli import cmd_drift_report
        cmd_drift_report()  # Should not raise

    def test_cmd_config_baseline_list_empty(self, tmp_path):
        """CLI config-baseline list handles empty state."""
        import os
        from argparse import Namespace
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.cli import cmd_config_baseline
        args = Namespace(config_baseline_command="list")
        cmd_config_baseline(args)  # Should not raise

    def test_cmd_config_baseline_show_nonexistent(self, tmp_path):
        """CLI config-baseline show handles missing baseline."""
        import os
        from argparse import Namespace
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.cli import cmd_config_baseline
        args = Namespace(config_baseline_command="show", name="no-such-agent")
        cmd_config_baseline(args)  # Should not raise

    def test_cmd_config_baseline_delete(self, tmp_path):
        """CLI config-baseline delete handles missing baseline."""
        import os
        from argparse import Namespace
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.cli import cmd_config_baseline
        args = Namespace(config_baseline_command="delete", name="no-such-agent")
        cmd_config_baseline(args)  # Should not raise

    def test_cmd_config_baseline_set(self, tmp_path):
        """CLI config-baseline set works with a real agent."""
        import os
        from argparse import Namespace
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import get_connection, upsert_agent
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="cli-baseline-agent", url="http://localhost:1",
            provider="openai", status=AgentStatus.ONLINE, tags=["test"],
        ))
        conn.close()

        from agent_control_plane.cli import cmd_config_baseline
        args = Namespace(
            config_baseline_command="set", name="cli-baseline-agent",
            provider="anthropic", health_path=None, version=None, tags=None,
        )
        cmd_config_baseline(args)  # Should not raise

    def test_cmd_config_baseline_show_with_data(self, tmp_path):
        """CLI config-baseline show displays existing baseline."""
        import os
        from argparse import Namespace
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import (
            get_connection,
            upsert_agent,
            upsert_config_baseline,
        )
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="show-me", url="http://localhost:1",
            provider="openai", status=AgentStatus.ONLINE, tags=["test"],
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="show-me", provider="openai",
            expected_version="gpt-4", expected_tags=["test"], captured_at=now,
        ))
        conn.close()

        from agent_control_plane.cli import cmd_config_baseline
        args = Namespace(config_baseline_command="show", name="show-me")
        cmd_config_baseline(args)  # Should not raise

    def test_cmd_config_baseline_list_with_data(self, tmp_path):
        """CLI config-baseline list displays baselines."""
        import os
        from argparse import Namespace
        os.environ["ACP_HOME"] = str(tmp_path)

        from agent_control_plane.inventory import (
            get_connection,
            upsert_agent,
            upsert_config_baseline,
        )
        from agent_control_plane.models import AgentRecord, AgentStatus

        conn = get_connection()
        now = datetime.now(UTC)
        upsert_agent(conn, AgentRecord(
            name="list-test", url="http://localhost:1",
            provider="openai", status=AgentStatus.ONLINE, tags=[],
        ))
        upsert_config_baseline(conn, ConfigBaseline(
            agent_name="list-test", provider="openai", captured_at=now,
        ))
        conn.close()

        from agent_control_plane.cli import cmd_config_baseline
        args = Namespace(config_baseline_command="list")
        cmd_config_baseline(args)  # Should not raise
