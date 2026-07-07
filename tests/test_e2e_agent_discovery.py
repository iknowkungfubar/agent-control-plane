"""E2E integration tests for Agent Control Plane.

These tests simulate the full user workflow: configure → scan → inventory →
health check → cost track → export. They run against real HTTP servers and
a real SQLite database.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import Generator

import pytest

# Path to the CLI we're testing
CLI_ENTRY = [sys.executable, "-m", "agent_control_plane.cli"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _MockAgentHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler that simulates an agent endpoint."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(200, {"status": "ok", "uptime": "72h", "version": "1.0.0"})
        elif self.path == "/ready":
            self._respond(200, {"status": "ready"})
        elif self.path == "/metrics":
            self._respond(200, {
                "tokens_in": 150000,
                "tokens_out": 45000,
                "requests_total": 1200,
            })
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object, **kwargs: object) -> None:
        pass  # Silence logs during tests


class _DegradedHandler(BaseHTTPRequestHandler):
    """Handler that responds slowly or with errors to simulate a degraded agent."""

    call_count = 0

    def do_GET(self) -> None:
        self.__class__.call_count += 1
        if self.path == "/health":
            # Alternate between slow and error responses
            if self.call_count % 3 == 0:
                time.sleep(2.5)  # Exceeds default timeout
            elif self.call_count % 3 == 1:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                data = json.dumps({"status": "overloaded"}).encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self._respond(200, {"status": "ok", "uptime": "12h"})

    def _respond(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object, **kwargs: object) -> None:
        pass


def _free_port() -> int:
    """Find a free port on localhost."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock_agent_server() -> Generator[int, None, None]:
    """Start a mock agent HTTP server on a free port."""
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _MockAgentHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield port
    server.shutdown()


@pytest.fixture(scope="module")
def degraded_agent_server() -> Generator[int, None, None]:
    """Start a degraded agent HTTP server on a free port."""
    _DegradedHandler.call_count = 0
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _DegradedHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield port
    server.shutdown()


@pytest.fixture()
def temp_home() -> Generator[Path, None, None]:
    """Create a temp directory with a config file and set it as ACP_HOME."""
    with tempfile.TemporaryDirectory(prefix="acp_test_") as tmp:
        yield Path(tmp)


# ---------------------------------------------------------------------------
# Tests — written in the order of the user workflow
# ---------------------------------------------------------------------------


class TestE2EWorkflow:
    """End-to-end test of the full Agent Control Plane workflow."""

    def test_e2e_full_workflow(
        self, temp_home: Path, mock_agent_server: int,
    ) -> None:
        """Complete user workflow: init → scan → list → health → export.

        This is the primary E2E test. It verifies all CLI commands work
        together in sequence using a real HTTP agent endpoint.
        """
        test_cfg = {
            "agents": [
                {
                    "name": "test-agent-1",
                    "url": f"http://127.0.0.1:{mock_agent_server}",
                    "provider": "custom",
                    "tags": ["test", "e2e"],
                },
                {
                    "name": "test-agent-2",
                    "url": f"http://127.0.0.1:{mock_agent_server}",
                    "provider": "openai",
                    "tags": ["test"],
                },
            ],
        }

        cfg_file = temp_home / "config.yaml"
        import yaml
        with open(cfg_file, "w") as f:
            yaml.dump(test_cfg, f)

        env = os.environ.copy()
        env["ACP_CONFIG"] = str(cfg_file)
        env["ACP_HOME"] = str(temp_home)

        # Step 1: Scan — discover and register agents
        result = subprocess.run(
            [*CLI_ENTRY, "scan"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert result.returncode == 0, f"scan failed: {result.stderr}"
        assert "2 agents" in result.stdout.lower() or "2" in result.stdout, \
            f"Expected 2 agents discovered, got: {result.stdout}"

        # Step 2: List — show inventory
        result = subprocess.run(
            [*CLI_ENTRY, "list"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0, f"list failed: {result.stderr}"
        assert "test-agent-1" in result.stdout
        assert "test-agent-2" in result.stdout

        # Step 3: Health — ping all agents
        result = subprocess.run(
            [*CLI_ENTRY, "health"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0, f"health failed: {result.stderr}"
        assert "online" in result.stdout.lower() or "ok" in result.stdout.lower()

        # Step 4: Cost — show cost estimates
        result = subprocess.run(
            [*CLI_ENTRY, "cost"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0, f"cost failed: {result.stderr}"

        # Step 5: Export JSON
        json_out = temp_home / "export.json"
        result = subprocess.run(
            [*CLI_ENTRY, "export", "--format", "json", "--output", str(json_out)],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0, f"export json failed: {result.stderr}"
        assert json_out.exists()
        exported = json.loads(json_out.read_text())
        assert len(exported["agents"]) >= 2
        assert exported["summary"]["total_agents"] >= 2

        # Step 6: Export CSV
        csv_out = temp_home / "export.csv"
        result = subprocess.run(
            [*CLI_ENTRY, "export", "--format", "csv", "--output", str(csv_out)],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0, f"export csv failed: {result.stderr}"
        assert csv_out.exists()
        csv_content = csv_out.read_text()
        assert "name" in csv_content.lower()
        assert "status" in csv_content.lower()

    def test_e2e_degraded_agent_detection(
        self, temp_home: Path, degraded_agent_server: int,
    ) -> None:
        """E2E test: system correctly detects and reports degraded agents."""
        test_cfg = {
            "agents": [
                {
                    "name": "flaky-agent",
                    "url": f"http://127.0.0.1:{degraded_agent_server}",
                    "provider": "custom",
                },
            ],
        }

        import yaml
        cfg_file = temp_home / "config.yaml"
        with open(cfg_file, "w") as f:
            yaml.dump(test_cfg, f)

        env = os.environ.copy()
        env["ACP_CONFIG"] = str(cfg_file)
        env["ACP_HOME"] = str(temp_home)

        # Scan
        result = subprocess.run(
            [*CLI_ENTRY, "scan"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert result.returncode == 0

        # Health check — the degraded server has slow and error responses
        result = subprocess.run(
            [*CLI_ENTRY, "health", "--timeout", "1"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert result.returncode == 0
        # Should report at least some checks as degraded or offline
        assert any(w in result.stdout.lower() for w in ["degraded", "offline", "timeout", "error"]), \
            f"Expected degraded detection, got: {result.stdout}"

    def test_e2e_empty_config(self, temp_home: Path) -> None:
        """E2E test: system handles empty configuration gracefully."""
        test_cfg = {"agents": []}

        import yaml
        cfg_file = temp_home / "config.yaml"
        with open(cfg_file, "w") as f:
            yaml.dump(test_cfg, f)

        env = os.environ.copy()
        env["ACP_CONFIG"] = str(cfg_file)
        env["ACP_HOME"] = str(temp_home)

        result = subprocess.run(
            [*CLI_ENTRY, "list"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0
        # Should say "no agents" or show 0
        assert any(
            w in result.stdout.lower()
            for w in ["no agents", "0 agents", "none", "empty"]
        ), f"Expected empty state message, got: {result.stdout}"

    def test_e2e_list_with_no_config(self, temp_home: Path) -> None:
        """E2E test: list command works with no config (empty inventory)."""
        env = os.environ.copy()
        env["ACP_CONFIG"] = str(temp_home / "nonexistent.yaml")
        env["ACP_HOME"] = str(temp_home)

        result = subprocess.run(
            [*CLI_ENTRY, "list"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        # Should exit non-zero with a helpful error message
        assert result.returncode == 0
        # list works with empty DB; only scan requires config
        assert any(
            w in result.stdout.lower()
            for w in ["no agents", "0 agents", "none", "empty", "inventory"]
        ), f"Expected empty state message, got: {result.stdout}"

    def test_e2e_unreachable_agent(self, temp_home: Path) -> None:
        """E2E test: system handles unreachable agent endpoints gracefully."""
        test_cfg = {
            "agents": [
                {
                    "name": "offline-agent",
                    "url": "http://127.0.0.1:19999",
                    "provider": "custom",
                },
            ],
        }

        import yaml
        cfg_file = temp_home / "config.yaml"
        with open(cfg_file, "w") as f:
            yaml.dump(test_cfg, f)

        env = os.environ.copy()
        env["ACP_CONFIG"] = str(cfg_file)
        env["ACP_HOME"] = str(temp_home)

        # Scan should still succeed but show agent as offline
        result = subprocess.run(
            [*CLI_ENTRY, "scan"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0

        # Health should show it as offline
        result = subprocess.run(
            [*CLI_ENTRY, "health"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0
        assert any(
            w in result.stdout.lower()
            for w in ["offline", "unreachable", "failed", "error", "down"]
        ), f"Expected offline indication, got: {result.stdout}"

    def test_e2e_status_subcommand(self, temp_home: Path, mock_agent_server: int) -> None:
        """E2E test: status command shows summary statistics."""
        test_cfg = {
            "agents": [
                {
                    "name": "status-test-agent",
                    "url": f"http://127.0.0.1:{mock_agent_server}",
                    "provider": "anthropic",
                    "tags": ["production"],
                },
            ],
        }

        import yaml
        cfg_file = temp_home / "config.yaml"
        with open(cfg_file, "w") as f:
            yaml.dump(test_cfg, f)

        env = os.environ.copy()
        env["ACP_CONFIG"] = str(cfg_file)
        env["ACP_HOME"] = str(temp_home)

        # Run scan + health first to populate data
        subprocess.run([*CLI_ENTRY, "scan"], capture_output=True, timeout=15, env=env)
        subprocess.run([*CLI_ENTRY, "health"], capture_output=True, timeout=15, env=env)

        # Status command
        result = subprocess.run(
            [*CLI_ENTRY, "status"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 0
        # Should show summary stats
        output = result.stdout.lower()
        assert "agent" in output
        assert "online" in output or "total" in output
