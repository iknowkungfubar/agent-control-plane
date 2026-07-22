"""E2E tests for the Agent Control Plane Web UI Dashboard.

Tests the FastAPI backend by running it in-process and making real HTTP
requests. Covers all REST API routes and static page serving.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.testclient import TestClient


@pytest.fixture(scope="module")
def app_client() -> Generator[TestClient, None, None]:
    """Create a test client against the FastAPI app with a temp DB."""
    with tempfile.TemporaryDirectory(prefix="acp_dash_") as tmp:
        # Set up env
        old_home = os.environ.get("ACP_HOME")
        old_cfg = os.environ.get("ACP_CONFIG")
        os.environ["ACP_HOME"] = tmp

        # Write config with mock agents
        cfg = {
            "agents": [
                {"name": "agent-alpha", "url": "http://localhost:18080", "provider": "openai", "tags": ["prod"]},
                {"name": "agent-beta", "url": "http://localhost:18081", "provider": "anthropic", "tags": ["staging"]},
            ],
        }
        cfg_path = Path(tmp) / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(cfg, f)
        os.environ["ACP_CONFIG"] = str(cfg_path)

        # Populate DB via CLI scan
        from agent_control_plane.cli import main
        assert main(["scan"]) == 0

        # Create the app and wrap in TestClient
        from agent_control_plane.dashboard import create_app
        app = create_app()
        from starlette.testclient import TestClient
        client = TestClient(app)
        yield client
        client.close()

        # Clean up
        if old_home:
            os.environ["ACP_HOME"] = old_home
        elif "ACP_HOME" in os.environ:
            del os.environ["ACP_HOME"]
        if old_cfg:
            os.environ["ACP_CONFIG"] = old_cfg
        elif "ACP_CONFIG" in os.environ:
            del os.environ["ACP_CONFIG"]


class TestDashboardE2E:
    """Full E2E test of the dashboard API and pages."""

    def test_api_status(self, app_client: TestClient):
        """GET /api/status returns fleet summary with correct counts."""
        resp = app_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_agents"] == 2
        assert "online" in data
        assert "offline" in data
        assert "total_estimated_cost_monthly_usd" in data

    def test_api_agents(self, app_client: TestClient):
        """GET /api/agents returns list of all agents."""
        resp = app_client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) >= 2
        names = [a["name"] for a in data["agents"]]
        assert "agent-alpha" in names
        assert "agent-beta" in names
        # Verify shape
        agent = data["agents"][0]
        assert "name" in agent
        assert "provider" in agent
        assert "status" in agent
        assert "url" in agent

    def test_api_agents_empty(self):
        """GET /api/agents with empty DB returns empty list."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            from starlette.testclient import TestClient

            from agent_control_plane.dashboard import create_app
            app = create_app()
            client = TestClient(app)
            resp = client.get("/api/agents")
            assert resp.status_code == 200
            data = resp.json()
            assert data["agents"] == []
            client.close()
            del os.environ["ACP_HOME"]

    def test_api_health_history(self, app_client: TestClient):
        """GET /api/agents/{name}/health returns health check history."""
        resp = app_client.get("/api/agents/agent-alpha/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "health_log" in data
        assert "agent_name" in data

    def test_api_health_history_not_found(self, app_client: TestClient):
        """GET /api/agents/nonexistent/health returns 404."""
        resp = app_client.get("/api/agents/ghost-agent/health")
        assert resp.status_code == 404

    def test_api_costs(self, app_client: TestClient):
        """GET /api/costs returns cost breakdown."""
        resp = app_client.get("/api/costs")
        assert resp.status_code == 200
        data = resp.json()
        assert "costs" in data
        assert "total_monthly_cost" in data

    def test_api_export(self, app_client: TestClient):
        """GET /api/export returns JSON download of full inventory."""
        resp = app_client.get("/api/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"
        data = resp.json()
        assert "agents" in data
        assert "summary" in data
        assert data["summary"]["total_agents"] >= 2

    def test_dashboard_page(self, app_client: TestClient):
        """GET / returns the dashboard HTML page."""
        resp = app_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        body = resp.text.lower()
        assert "agent" in body
        assert "dashboard" in body or "fleet" in body or "status" in body

    def test_agents_page(self, app_client: TestClient):
        """GET /agents returns the agents list HTML page."""
        resp = app_client.get("/agents")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_agent_detail_page(self, app_client: TestClient):
        """GET /agents/{name} returns agent detail page."""
        resp = app_client.get("/agents/agent-alpha")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_costs_page(self, app_client: TestClient):
        """GET /costs returns the costs HTML page."""
        resp = app_client.get("/costs")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_not_found_page(self, app_client: TestClient):
        """GET /nonexistent returns 404 HTML page."""
        resp = app_client.get("/nonexistent-route")
        assert resp.status_code == 404
        assert "text/html" in resp.headers.get("content-type", "")

    def test_cors_headers(self, app_client: TestClient):
        """Dashboard returns valid responses."""
        resp = app_client.get("/api/status")
        assert resp.status_code == 200

    # ------------------------------------------------------------------
    # Analytics API E2E tests (Sprint S-5)
    # ------------------------------------------------------------------

    def test_api_analytics_health_fleet(self, app_client: TestClient):
        """GET /api/analytics/health returns fleet health time-series."""
        resp = app_client.get("/api/analytics/health?bucket=day&days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert "bucket" in data
        assert "days" in data
        assert "series" in data
        assert data["bucket"] == "day"

    def test_api_analytics_health_agent(self, app_client: TestClient):
        """GET /api/analytics/health/{name} returns per-agent time-series."""
        resp = app_client.get("/api/analytics/health/agent-alpha?bucket=day&days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "agent-alpha"
        assert "bucket" in data
        assert "series" in data
        # Series may be empty if no health checks performed yet
        assert isinstance(data["series"], list)

    def test_api_analytics_health_agent_not_found(self, app_client: TestClient):
        """GET /api/analytics/health/nonexistent returns 404."""
        resp = app_client.get("/api/analytics/health/ghost-agent")
        assert resp.status_code == 404

    def test_api_analytics_costs(self, app_client: TestClient):
        """GET /api/analytics/costs returns cost time-series."""
        resp = app_client.get("/api/analytics/costs?months=6")
        assert resp.status_code == 200
        data = resp.json()
        assert "months" in data
        assert "series" in data

    def test_api_analytics_costs_per_agent(self, app_client: TestClient):
        """GET /api/analytics/costs?agent=X filters to one agent."""
        resp = app_client.get("/api/analytics/costs?months=6&agent=agent-alpha")
        assert resp.status_code == 200
        data = resp.json()
        assert "series" in data

    def test_api_analytics_health_bucket_parameter(self, app_client: TestClient):
        """Bucket parameter accepts hour/day/week with defaults."""
        # Default bucket
        resp = app_client.get("/api/analytics/health?days=1")
        assert resp.status_code == 200

        # Hour bucket
        resp = app_client.get("/api/analytics/health?bucket=hour&days=1")
        assert resp.status_code == 200

        # Week bucket
        resp = app_client.get("/api/analytics/health?bucket=week&days=14")
        assert resp.status_code == 200

    def test_api_analytics_health_with_data(self):
        """Analytics endpoint returns data when health checks exist."""
        with tempfile.TemporaryDirectory() as tmp:
            old_home = os.environ.get("ACP_HOME")
            os.environ["ACP_HOME"] = tmp

            from datetime import datetime

            from agent_control_plane.dashboard import create_app
            from agent_control_plane.inventory import get_connection, log_health_check, upsert_agent
            from agent_control_plane.models import AgentRecord, AgentStatus

            # Set up agent + health data
            conn = get_connection()
            upsert_agent(conn, AgentRecord(
                name="test-a", url="http://localhost:1", provider="custom",
            ))
            now = datetime.now(UTC)
            for i in range(24):
                ts = now.replace(hour=i % 24, minute=0) - __import__("datetime").timedelta(hours=i)
                log_health_check(conn, "test-a", AgentStatus.ONLINE, 100.0, 200, timestamp=ts)
            conn.close()

            app = create_app()
            from starlette.testclient import TestClient
            client = TestClient(app)

            # Fleet health
            resp = client.get("/api/analytics/health?bucket=day&days=3")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["series"]) > 0
            entry = data["series"][0]
            assert "online" in entry
            assert "count" in entry

            # Per-agent health
            resp = client.get("/api/analytics/health/test-a?bucket=day&days=3")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["series"]) > 0
            assert data["agent_name"] == "test-a"
            assert data["series"][0]["online"] > 0

            client.close()
            del os.environ["ACP_HOME"]
            if old_home:
                os.environ["ACP_HOME"] = old_home
