"""Unit tests for discovery module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml


class TestGetConfiguredAgents:
    """Test loading configured agents from config file."""

    def test_get_configured_agents(self):
        """Load agents from a valid config file."""
        from agent_control_plane.discovery import get_configured_agents

        cfg = {
            "agents": [
                {"name": "agent-a", "url": "http://localhost:8000", "provider": "openai"},
                {"name": "agent-b", "url": "http://localhost:8001", "provider": "anthropic"},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(cfg, f)
            cfg_path = f.name

        try:
            os.environ["ACP_CONFIG"] = cfg_path
            agents = get_configured_agents()
            assert len(agents) == 2
            assert agents[0].name == "agent-a"
            assert agents[1].provider == "anthropic"
        finally:
            Path(cfg_path).unlink()
            del os.environ["ACP_CONFIG"]

    def test_empty_config_returns_empty(self):
        """Empty config returns empty agent list."""
        from agent_control_plane.discovery import parse_agents

        agents = parse_agents({})
        assert agents == []

    def test_no_agents_key_returns_empty(self):
        """Config without agents key returns empty list."""
        from agent_control_plane.discovery import parse_agents

        agents = parse_agents({"other": "data"})
        assert agents == []


class TestScanPorts:
    """Test parallel and sequential port scanning."""

    @pytest.fixture
    def mock_agent_server(self):
        """Start a real HTTP server that responds like an OpenAI-compatible agent."""
        import http.server
        import json
        import threading
        import time

        class MockAgentHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/v1/models", "/health"):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"data": [{"id": "gpt-4"}]}).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), MockAgentHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        yield port
        server.shutdown()

    def test_scan_ports_parallel_finds_agent(self, mock_agent_server):
        """scan_ports with max_workers finds the live agent endpoint."""
        from agent_control_plane.discovery.scanner import _clear_cache, scan_ports

        _clear_cache()
        ports = [mock_agent_server, mock_agent_server + 1, mock_agent_server + 2]
        results = scan_ports("127.0.0.1", ports, timeout=2.0, max_workers=4)
        assert len(results) == 1
        assert results[0]["provider"] == "openai"
        assert results[0]["port"] == mock_agent_server

    def test_scan_ports_sequential_finds_agent(self, mock_agent_server):
        """scan_ports with max_workers=1 (sequential) finds the live agent."""
        from agent_control_plane.discovery.scanner import _clear_cache, scan_ports

        _clear_cache()
        ports = [mock_agent_server, mock_agent_server + 1]
        results = scan_ports("127.0.0.1", ports, timeout=2.0, max_workers=1)
        assert len(results) == 1
        assert results[0]["port"] == mock_agent_server

    def test_scan_ports_no_open_ports(self):
        """scan_ports returns empty list when nothing responds."""
        from agent_control_plane.discovery.scanner import _clear_cache, scan_ports

        _clear_cache()
        # Port 1 is almost always closed
        results = scan_ports("127.0.0.1", [1, 2], timeout=0.5, max_workers=3)
        assert results == []


class TestSyncInventory:
    """Test syncing configured agents to inventory database."""

    def test_sync_inventory_new_agents(self):
        """Sync adds new agents to DB."""
        from agent_control_plane.discovery import sync_inventory

        cfg = {"agents": [{"name": "new-agent", "url": "http://localhost:9000"}]}

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            cfg_path = Path(tmp) / "config.yaml"
            with open(cfg_path, "w") as f:
                yaml.dump(cfg, f)
            os.environ["ACP_CONFIG"] = str(cfg_path)

            agents = sync_inventory()
            assert len(agents) == 1
            assert agents[0].name == "new-agent"
            assert agents[0].status.value == "unknown"

            # Verify it persisted by calling sync again
            agents2 = sync_inventory()
            assert len(agents2) == 1

            del os.environ["ACP_CONFIG"]
            del os.environ["ACP_HOME"]
