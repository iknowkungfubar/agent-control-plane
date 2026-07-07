"""Unit tests for the export module."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from agent_control_plane.exporter import build_export_data


@pytest.fixture(autouse=True)
def _setup_env():
    """Set ACP_HOME to a temp dir for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        old_home = os.environ.get("ACP_HOME")
        os.environ["ACP_HOME"] = tmp
        yield
        if old_home:
            os.environ["ACP_HOME"] = old_home
        else:
            del os.environ["ACP_HOME"]


class TestExport:
    """Test export data building and file output."""

    def test_build_export_data_empty(self):
        """Empty inventory produces valid export structure."""
        data = build_export_data()
        assert "exported_at" in data
        assert "summary" in data
        assert "agents" in data
        assert "costs" in data
        assert data["summary"]["total_agents"] == 0

    def test_export_json_creates_file(self):
        """JSON export creates a valid JSON file."""
        from agent_control_plane.exporter import export_json
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.json"
            result = export_json(out)
            assert result == out
            assert out.exists()
            parsed = json.loads(out.read_text())
            assert "summary" in parsed

    def test_export_csv_creates_file(self):
        """CSV export creates a valid CSV file."""
        from agent_control_plane.exporter import export_csv
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.csv"
            result = export_csv(out)
            assert result == out
            assert out.exists()
            content = out.read_text()
            assert "name" in content
