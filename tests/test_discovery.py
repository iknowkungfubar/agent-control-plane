"""Unit tests for discovery module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from agent_control_plane.models import AgentEndpoint


class TestGetConfiguredAgents:
    """Test loading configured agents from config file."""

    def test_get_configured_agents(self):
        """Load agents from a valid config file."""
        from agent_control_plane.discovery import get_configured_agents
        cfg = {
            "agents": [
                {"name": "agent-a", "url": "http://localhost:8000", "provider": "openai"},
                {"name": "agent-b", "url": "http://localhost:8001", "provider": "anthropic"},
            ]
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
            os.unlink(cfg_path)
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
