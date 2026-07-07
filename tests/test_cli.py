"""Unit tests for CLI module."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from agent_control_plane.cli import main


class TestCLICommands:
    """Test CLI command dispatch."""

    def test_version(self):
        """--version flag prints version and exits."""
        with pytest.raises(SystemExit):
            main(["--version"])

    def test_no_args_shows_help(self):
        """No arguments prints help and exits 0."""
        rc = main([])
        assert rc == 0

    def test_status_empty(self):
        """Status with empty DB shows appropriate message."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            rc = main(["status"])
            assert rc == 0
            del os.environ["ACP_HOME"]

    def test_list_empty(self):
        """List with empty DB shows no agents message."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            rc = main(["list"])
            assert rc == 0
            del os.environ["ACP_HOME"]

    def test_scan_no_config(self):
        """Scan without config file shows error message."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            rc = main(["scan"])
            assert rc == 1  # Error: no config file
            del os.environ["ACP_HOME"]

    def test_health_no_config(self):
        """Health without config shows error."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            rc = main(["health"])
            assert rc == 1  # Error: no config file
            del os.environ["ACP_HOME"]

    def test_unknown_command(self):
        """Unknown command exits with non-zero status."""
        with pytest.raises(SystemExit) as exc:
            main(["unknown-command"])
        assert exc.value.code != 0

    def test_cost_no_data(self):
        """Cost with no data shows appropriate message."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            rc = main(["cost"])
            assert rc == 0
            del os.environ["ACP_HOME"]

    def test_scan_with_config(self):
        """Scan with valid config succeeds."""
        cfg = {"agents": [{"name": "cfg-agent", "url": "http://localhost:9999"}]}
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.yaml"
            with open(cfg_path, "w") as f:
                yaml.dump(cfg, f)
            os.environ["ACP_CONFIG"] = str(cfg_path)
            os.environ["ACP_HOME"] = tmp
            rc = main(["scan"])
            assert rc == 0
            del os.environ["ACP_CONFIG"]
            del os.environ["ACP_HOME"]

    def test_export_requires_output(self):
        """Export without output path uses default."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            rc = main(["export", "--format", "json"])
            assert rc == 0
            # Check default export file exists
            assert (Path(tmp) / "acp-export.json").exists()
            del os.environ["ACP_HOME"]

    def test_export_csv(self):
        """Export CSV works."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ACP_HOME"] = tmp
            out = Path(tmp) / "agents.csv"
            rc = main(["export", "--format", "csv", "--output", str(out)])
            assert rc == 0
            assert out.exists()
            del os.environ["ACP_HOME"]
