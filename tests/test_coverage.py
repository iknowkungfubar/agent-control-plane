"""Additional tests to boost coverage — health, cost, and CLI edge cases."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from datetime import UTC
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest
import yaml

from agent_control_plane.models import AgentEndpoint


@pytest.fixture(autouse=True)
def temp_acp_home():
    """Set ACP_HOME to a temp directory for every test."""
    with tempfile.TemporaryDirectory() as tmp:
        old_home = os.environ.get("ACP_HOME")
        old_cfg = os.environ.get("ACP_CONFIG")
        os.environ["ACP_HOME"] = tmp
        yield
        if old_home:
            os.environ["ACP_HOME"] = old_home
        else:
            del os.environ["ACP_HOME"]
        if old_cfg:
            os.environ["ACP_CONFIG"] = old_cfg
        elif "ACP_CONFIG" in os.environ:
            del os.environ["ACP_CONFIG"]


class _DegradedHandler(BaseHTTPRequestHandler):
    """Handler returning degraded status JSON."""

    def do_GET(self):
        if self.path == "/health":
            data = json.dumps({"status": "degraded", "reason": "high latency"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def degraded_port() -> Generator[int, None, None]:
    """Server returning degraded health status."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = HTTPServer(("127.0.0.1", port), _DegradedHandler)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield port
    server.shutdown()


class TestCoverageHealth:
    """Boost health module coverage."""

    def test_degraded_detection(self, degraded_port: int):
        """Agent returning 'degraded' status in JSON is detected."""
        from agent_control_plane.health import check_agent_health
        ep = AgentEndpoint(name="deg", url=f"http://127.0.0.1:{degraded_port}")
        status, elapsed, code, error = check_agent_health(ep)
        assert status.value == "degraded"

    def test_malformed_json(self):
        """Non-JSON response still counts as online."""
        # Connect to something that doesn't return JSON
        import socket

        from agent_control_plane.health import check_agent_health
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        s.settimeout(0.5)

        def _respond():
            import time
            time.sleep(0.1)
            conn, _ = s.accept()
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
            conn.close()
            s.close()

        Thread(target=_respond, daemon=True).start()
        ep = AgentEndpoint(name="raw", url=f"http://127.0.0.1:{port}")
        status, elapsed, code, error = check_agent_health(ep, timeout=3)
        assert status.value == "online"

    def test_unexpected_status_code(self, degraded_port: int):
        """Non-200 but <500 status code shows as degraded."""
        from agent_control_plane.health import check_agent_health
        ep = AgentEndpoint(name="notfound", url=f"http://127.0.0.1:{degraded_port}", health_check_path="/nope")
        status, _, code, _ = check_agent_health(ep)
        assert status.value == "degraded"
        assert code == 404


class TestCoverageCost:
    """Boost cost tracker coverage."""

    def test_record_and_retrieve_cost(self):
        """record_cost persists and get_all_costs retrieves."""
        from agent_control_plane.cost_tracker import get_all_costs, record_cost, total_monthly_cost
        record_cost("cost-test", "openai", 500000, 100000)
        records = get_all_costs()
        assert len(records) == 1
        assert records[0].agent_name == "cost-test"
        total = total_monthly_cost()
        assert total > 0

    def test_record_multiple_months(self):
        """Cost records for different months both appear."""
        from datetime import datetime

        from agent_control_plane.cost_tracker import get_all_costs, record_cost
        from agent_control_plane.inventory import get_connection, upsert_cost_record
        from agent_control_plane.models import CostRecord

        # Use direct DB insert for a different month
        conn = get_connection()
        upsert_cost_record(conn, CostRecord(
            agent_name="old", month="2026-01", estimated_cost_usd=50.0,
            last_updated=datetime.now(UTC),
        ))
        conn.close()

        record_cost("new", "anthropic", 100000, 50000)
        records = get_all_costs()
        assert len(records) >= 2

    def test_provider_rates(self):
        """All cost rates are non-negative."""
        from agent_control_plane.cost_tracker import (
            PROVIDER_COST_PER_1K_IN,
            PROVIDER_COST_PER_1K_OUT,
        )
        for provider, rate in PROVIDER_COST_PER_1K_IN.items():
            assert rate >= 0, f"Negative in rate for {provider}"
        for provider, rate in PROVIDER_COST_PER_1K_OUT.items():
            assert rate >= 0, f"Negative out rate for {provider}"


class TestCoverageCLI:
    """Boosting CLI coverage by exercising more code paths."""

    def test_delete_nonexistent(self):
        """Delete non-existent agent doesn't crash."""
        from agent_control_plane.cli import main
        rc = main(["delete", "ghost-agent"])
        assert rc == 0

    def test_scan_then_list_then_status(self):
        """Full workflow via CLI main() -> scan, list, status."""
        from agent_control_plane.cli import main

        cfg = {"agents": [{"name": "cli-test", "url": "http://localhost:1111"}]}
        cfg_path = Path(os.environ["ACP_HOME"]) / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(cfg, f)
        os.environ["ACP_CONFIG"] = str(cfg_path)

        # scan
        assert main(["scan"]) == 0
        # list
        assert main(["list"]) == 0
        # status
        assert main(["status"]) == 0

    def test_health_endpoint_timing(self):
        """CLI health with --timeout flag."""
        from agent_control_plane.cli import main

        cfg = {"agents": [{"name": "fast", "url": "http://127.0.0.1:1"}]}
        cfg_path = Path(os.environ["ACP_HOME"]) / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(cfg, f)
        os.environ["ACP_CONFIG"] = str(cfg_path)

        # Should not crash — agent is unreachable but health handles it
        rc = main(["health", "--timeout", "1"])
        assert rc == 0


class TestCoverageDiscovery:
    """Boost discovery coverage."""

    def test_sync_inventory_file_not_found(self):
        """sync_inventory with no config raises FileNotFoundError."""
        from agent_control_plane.discovery import sync_inventory
        with pytest.raises(FileNotFoundError):
            sync_inventory()
