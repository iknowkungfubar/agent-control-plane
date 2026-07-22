"""E2E tests for automatic agent discovery (network scan + MCP detection).

Tests the full discovery workflow: local port scanning, HTTP response
inspection for provider identification, and registration to inventory.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Generator

TEST_PROVIDER_PORTS: dict[str, int] = {}


class _OpenAIishHandler(BaseHTTPRequestHandler):
    """Simulates an OpenAI-compatible API endpoint."""

    def do_GET(self):
        if self.path == "/v1/models":
            data = json.dumps({"data": [{"id": "gpt-4"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/health":
            data = json.dumps({"status": "ok"}).encode()
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


class _AnthropicishHandler(BaseHTTPRequestHandler):
    """Simulates an Anthropic-compatible API endpoint."""

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            data = json.dumps({"status": "ok"}).encode()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class _MCPStdioHandler(BaseHTTPRequestHandler):
    """Simulates a basic MCP server endpoint."""

    def do_GET(self):
        if self.path in {"/mcp", "/"}:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            data = json.dumps({
                "server": {"name": "test-mcp", "version": "1.0.0"},
                "tools": [{"name": "echo", "description": "Echo input"}],
            }).encode()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def openai_server() -> Generator[int, None, None]:
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _OpenAIishHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    yield port
    server.shutdown()


@pytest.fixture(scope="module")
def anthropic_server() -> Generator[int, None, None]:
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _AnthropicishHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    yield port
    server.shutdown()


@pytest.fixture(scope="module")
def mcp_server() -> Generator[int, None, None]:
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _MCPStdioHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    yield port
    server.shutdown()


@pytest.fixture(autouse=True)
def _temp_env():
    """Temp ACP_HOME for each test."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="acp_disc_") as tmp:
        old_home = os.environ.get("ACP_HOME")
        old_cfg = os.environ.get("ACP_CONFIG")
        os.environ["ACP_HOME"] = tmp
        # Minimal config
        cfg = {"agents": []}
        cfg_path = Path(tmp) / "config.yaml"
        with open(cfg_path, "w") as f:
            yaml.dump(cfg, f)
        os.environ["ACP_CONFIG"] = str(cfg_path)
        yield
        if old_home:
            os.environ["ACP_HOME"] = old_home
        elif "ACP_HOME" in os.environ:
            del os.environ["ACP_HOME"]
        if old_cfg:
            os.environ["ACP_CONFIG"] = old_cfg
        elif "ACP_CONFIG" in os.environ:
            del os.environ["ACP_CONFIG"]


class TestPortScanDiscovery:
    """Test network port scanning discovers agent endpoints."""

    def setup_method(self, method):
        from agent_control_plane.discovery.scanner import _clear_cache
        _clear_cache()

    def test_discover_openai_endpoint(self, openai_server: int):
        """Port scan discovers an OpenAI-compatible endpoint and identifies it."""
        from agent_control_plane.discovery.scanner import probe_endpoint
        result = probe_endpoint("127.0.0.1", openai_server)
        assert result is not None
        assert result["name"].startswith("agent-")
        assert "openai" in result["provider"].lower() or "openai" in str(result).lower()

    def test_discover_anthropic_endpoint(self, anthropic_server: int):
        """Port scan discovers an Anthropic endpoint."""
        from agent_control_plane.discovery.scanner import probe_endpoint
        result = probe_endpoint("127.0.0.1", anthropic_server)
        assert result is not None

    def test_scan_port_range_discovers_agents(
        self, openai_server: int, anthropic_server: int,
    ):
        """Scanning a port range discovers multiple agents."""
        from agent_control_plane.discovery.scanner import scan_ports
        ports = [openai_server, anthropic_server]
        results = scan_ports("127.0.0.1", ports)
        assert len(results) >= 2

    def test_scan_closed_port_returns_none(self):
        """Scanning a closed port returns no result."""
        from agent_control_plane.discovery.scanner import probe_endpoint
        result = probe_endpoint("127.0.0.1", 1)  # port 1 is closed
        assert result is None

    def test_register_discovered_agent(self, openai_server: int):
        """Discovered agent can be registered into inventory."""
        from agent_control_plane.discovery.scanner import probe_endpoint, register_discovered
        result = probe_endpoint("127.0.0.1", openai_server)
        assert result is not None
        record = register_discovered(result)
        assert record.name == result["name"]
        assert record.provider is not None

        # Verify it's in inventory
        from agent_control_plane.inventory import get_connection, list_agents
        conn = get_connection()
        agents = list_agents(conn)
        conn.close()
        names = [a.name for a in agents]
        assert result["name"] in names


class TestMCPDetection:
    """Test MCP server auto-detection."""

    def setup_method(self, method):
        from agent_control_plane.discovery.scanner import _clear_cache
        _clear_cache()

    def test_discover_mcp_server(self, mcp_server: int):
        """MCP server is detected via HTTP probe."""
        from agent_control_plane.discovery.scanner import probe_endpoint
        result = probe_endpoint("127.0.0.1", mcp_server)
        assert result is not None
        assert "name" in result
        assert "provider" in result

    def test_scan_mcp_port_range(self, mcp_server: int):
        """Scanning MCP port ranges discovers MCP servers."""
        from agent_control_plane.discovery.scanner import scan_ports
        results = scan_ports("127.0.0.1", [mcp_server])
        assert len(results) >= 1


class TestDiscoveryCLI:
    """Test the CLI discover command."""

    def setup_method(self, method):
        from agent_control_plane.discovery.scanner import _clear_cache
        _clear_cache()

    def test_discover_cli_basic(self, openai_server: int):
        """CLI discover command scans and reports findings."""

        from agent_control_plane.cli import main
        rc = main(["discover", "--host", "127.0.0.1", "--ports", str(openai_server)])
        assert rc == 0

    def test_discover_with_register(self, openai_server: int):
        """CLI discover --register adds agents to inventory."""
        from agent_control_plane.cli import main
        rc = main([
            "discover", "--host", "127.0.0.1",
            "--ports", str(openai_server),
            "--register",
        ])
        assert rc == 0

        # Verify in inventory
        from agent_control_plane.inventory import get_connection, list_agents
        conn = get_connection()
        agents = list_agents(conn)
        conn.close()
        assert len(agents) >= 1
