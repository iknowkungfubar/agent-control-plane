"""Unit tests for config module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from agent_control_plane.config import _resolve_home, _resolve_config_path, load_config, parse_agents
from agent_control_plane.models import AgentEndpoint


class TestConfigResolution:
    """Test config file and home directory resolution."""

    def test_resolve_home_default(self):
        """Without ACP_HOME, defaults to ~/.acp."""
        if "ACP_HOME" in os.environ:
            del os.environ["ACP_HOME"]
        path = _resolve_home()
        assert str(path).endswith("/.acp")

    def test_resolve_home_env(self):
        """ACP_HOME env var overrides default."""
        os.environ["ACP_HOME"] = "/custom/acp"
        path = _resolve_home()
        assert str(path) == "/custom/acp"
        del os.environ["ACP_HOME"]

    def test_resolve_config_default(self):
        """Without ACP_CONFIG, defaults to ACP_HOME/config.yaml."""
        if "ACP_CONFIG" in os.environ:
            del os.environ["ACP_CONFIG"]
        os.environ["ACP_HOME"] = "/tmp/test-acp"
        path = _resolve_config_path()
        assert str(path) == "/tmp/test-acp/config.yaml"
        del os.environ["ACP_HOME"]

    def test_resolve_config_env(self):
        """ACP_CONFIG env var overrides default."""
        os.environ["ACP_CONFIG"] = "/custom/config.yaml"
        path = _resolve_config_path()
        assert str(path) == "/custom/config.yaml"
        del os.environ["ACP_CONFIG"]


class TestLoadConfig:
    """Test config file loading."""

    def test_load_valid_yaml(self):
        """Valid YAML config loads correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"agents": [{"name": "test", "url": "http://example.com"}]}, f)
            temp_path = f.name

        try:
            cfg = load_config(Path(temp_path))
            assert cfg["agents"][0]["name"] == "test"
        finally:
            os.unlink(temp_path)

    def test_load_missing_file(self):
        """Missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent/config.yaml"))

    def test_load_empty_yaml(self):
        """Empty YAML file returns empty dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            temp_path = f.name

        try:
            cfg = load_config(Path(temp_path))
            assert cfg == {}
        finally:
            os.unlink(temp_path)


class TestParseAgents:
    """Test agent endpoint parsing."""

    def test_parse_single_agent(self):
        """Single agent parsed correctly."""
        cfg = {"agents": [{"name": "agent1", "url": "http://localhost:8080"}]}
        agents = parse_agents(cfg)
        assert len(agents) == 1
        assert agents[0].name == "agent1"
        assert agents[0].provider == "custom"
        assert agents[0].tags == []

    def test_parse_multiple_agents(self):
        """Multiple agents parsed correctly."""
        cfg = {
            "agents": [
                {"name": "a1", "url": "http://localhost:1", "provider": "openai", "tags": ["prod"]},
                {"name": "a2", "url": "http://localhost:2", "provider": "anthropic"},
            ]
        }
        agents = parse_agents(cfg)
        assert len(agents) == 2
        assert agents[0].provider == "openai"
        assert agents[0].tags == ["prod"]
        assert agents[1].provider == "anthropic"

    def test_parse_empty_agents(self):
        """Empty agents list returns empty list."""
        agents = parse_agents({})
        assert agents == []

    def test_health_url_property(self):
        """health_url property constructs correctly."""
        ep = AgentEndpoint(name="t", url="http://localhost:8080", health_check_path="/healthz")
        assert ep.health_url == "http://localhost:8080/healthz"

    def test_health_url_trailing_slash(self):
        """health_url handles trailing slash on base URL."""
        ep = AgentEndpoint(name="t", url="http://localhost:8080/")
        assert ep.health_url == "http://localhost:8080/health"
