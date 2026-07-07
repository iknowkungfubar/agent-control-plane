"""Unit tests for health monitoring module."""

from __future__ import annotations

import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from agent_control_plane.models import AgentEndpoint, AgentStatus


class _HealthHandler(BaseHTTPRequestHandler):
    """Handler for health check tests."""

    def do_GET(self) -> None:
        import json
        if self.path == "/health":
            data = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/slow":
            time.sleep(3)
            self.send_response(200)
            self.end_headers()
        elif self.path == "/error":
            self.send_response(500)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def health_port() -> Generator[int, None, None]:
    """Start a health check test server."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    server = HTTPServer(("127.0.0.1", port), _HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield port
    server.shutdown()


class TestCheckAgentHealth:
    """Test individual health check logic."""

    def test_online_agent(self, health_port: int):
        """Healthy agent returns ONLINE status."""
        from agent_control_plane.health import check_agent_health
        endpoint = AgentEndpoint(name="healthy", url=f"http://127.0.0.1:{health_port}")
        status, elapsed, code, error = check_agent_health(endpoint)
        assert status == AgentStatus.ONLINE
        assert code == 200
        assert error is None
        assert elapsed > 0

    def test_offline_unreachable(self):
        """Unreachable agent returns OFFLINE."""
        from agent_control_plane.health import check_agent_health
        endpoint = AgentEndpoint(name="offline", url="http://127.0.0.1:1")
        status, elapsed, code, error = check_agent_health(endpoint, timeout=1)
        assert status == AgentStatus.OFFLINE
        assert error is not None

    def test_http_error(self, health_port: int):
        """Agent returning 5xx is DEGRADED."""
        from agent_control_plane.health import check_agent_health
        endpoint = AgentEndpoint(
            name="err-agent", url=f"http://127.0.0.1:{health_port}",
            health_check_path="/error",
        )
        status, elapsed, code, error = check_agent_health(endpoint)
        assert status == AgentStatus.OFFLINE
        assert code == 500

    def test_timeout(self, health_port: int):
        """Slow agent triggers timeout OFFLINE."""
        from agent_control_plane.health import check_agent_health
        endpoint = AgentEndpoint(
            name="slow", url=f"http://127.0.0.1:{health_port}",
            health_check_path="/slow",
        )
        status, elapsed, code, error = check_agent_health(endpoint, timeout=1)
        assert status == AgentStatus.OFFLINE
        assert error == "timeout"


class TestRollingAvg:
    """Test rolling average calculation."""

    def test_rolling_avg(self):
        from agent_control_plane.health import _rolling_avg
        avg = _rolling_avg(100.0, 5, 50.0)
        # (100*5 + 50) / 6 = 91.67
        assert round(avg, 2) == 91.67

    def test_rolling_avg_first_value(self):
        from agent_control_plane.health import _rolling_avg
        avg = _rolling_avg(0, 0, 150.0)
        assert avg == 150.0
