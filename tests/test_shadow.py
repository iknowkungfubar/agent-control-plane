"""Tests for Shadow AI / SaaS discovery."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agent_control_plane.models import ShadowService

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fingerprint database tests
# ---------------------------------------------------------------------------


class TestFingerprintDB:
    def test_fingerprint_db_has_entries(self):
        """Fingerprint DB has 100+ entries."""
        from agent_control_plane.fingerprints import FINGERPRINT_DB
        assert len(FINGERPRINT_DB) >= 40  # 40+ fingerprint entries

    def test_each_fingerprint_has_required_fields(self):
        """Each fingerprint has name, category, paths, risk."""
        from agent_control_plane.fingerprints import FINGERPRINT_DB
        required = {"name", "category", "paths", "body_patterns", "header_patterns", "port_hints", "risk"}
        for fp in FINGERPRINT_DB:
            for field in required:
                assert field in fp, f"Missing {field} in {fp.get('name', 'unknown')}"

    def test_get_fingerprints_by_category(self):
        """Filtering by category works."""
        from agent_control_plane.fingerprints import get_fingerprints_by_category
        ai_apis = get_fingerprints_by_category("ai-api")
        assert len(ai_apis) >= 5

    def test_get_fingerprints_by_port(self):
        """Filtering by port works."""
        from agent_control_plane.fingerprints import get_fingerprints_by_port
        ollama_ports = get_fingerprints_by_port(11434)
        assert any("Ollama" in f["name"] for f in ollama_ports)

    def test_get_all_ports(self):
        """All ports returns a set of ints."""
        from agent_control_plane.fingerprints import get_all_ports
        ports = get_all_ports()
        assert len(ports) >= 10
        assert all(isinstance(p, int) for p in ports)

    def test_classify_risk_defaults(self):
        """Classify risk returns expected defaults."""
        from agent_control_plane.fingerprints import classify_risk
        assert classify_risk("self-hosted-llm") == "critical"
        assert classify_risk("mcp-server") == "high"
        assert classify_risk("ai-dev-tool") == "low"
        assert classify_risk("ai-api") == "medium"
        assert classify_risk("unknown") == "unknown"

    def test_classify_risk_auth_adjusts_down(self):
        """Auth-required services get lower risk."""
        from agent_control_plane.fingerprints import classify_risk
        assert classify_risk("self-hosted-llm", auth_required=True) == "medium"
        assert classify_risk("mcp-server", auth_required=True) == "medium"

    def test_match_fingerprint_openai(self):
        """Match fingerprint detects OpenAI-compatible API."""
        from agent_control_plane.fingerprints import match_fingerprint
        result = match_fingerprint(
            url="http://localhost:8000/v1/models",
            status_code=200,
            body='{"object": "list", "data": [{"id": "gpt-4"}]}',
            headers={"server": "openai"},
            port=8000,
        )
        assert result is not None
        assert "openai" in result["name"].lower()


class TestMatchFingerprint:
    def test_match_vllm(self):
        """Match fingerprint detects vLLM via body and header."""
        from agent_control_plane.fingerprints import match_fingerprint
        result = match_fingerprint(
            url="http://localhost:8000/health",
            status_code=200,
            body='{"status": "ok", "version": "vllm 0.6.0"}',
            headers={"server": "vllm"},
            port=8000,
        )
        assert result is not None
        assert "vllm" in result["name"].lower()

    def test_match_ollama(self):
        """Match fingerprint detects Ollama."""
        from agent_control_plane.fingerprints import match_fingerprint
        result = match_fingerprint(
            url="http://localhost:11434/api/tags",
            status_code=200,
            body='{"models": [{"name": "llama3"}]}',
            headers={},
            port=11434,
        )
        assert result is not None
        assert "Ollama" in result["name"]

    def test_no_match_unknown(self):
        """No match returns None for unrecognized services."""
        from agent_control_plane.fingerprints import match_fingerprint
        result = match_fingerprint(
            url="http://localhost:9999/",
            status_code=200,
            body="<html>nginx</html>",
            headers={"server": "nginx"},
            port=9999,
        )
        # Port 9999 is not in any fingerprint's port_hints
        assert result is None


# ---------------------------------------------------------------------------
# Shadow Service model tests
# ---------------------------------------------------------------------------


class TestShadowServiceModel:
    def test_shadow_service_defaults(self):
        """ShadowService has sensible defaults."""
        svc = ShadowService(name="Test", url="http://test:8080")
        assert svc.service_type == "unknown"
        assert svc.risk == "unknown"
        assert svc.discovered_by == ""
        assert svc.tags == []

    def test_shadow_service_with_all_fields(self):
        """ShadowService accepts all fields."""
        now = datetime.now(UTC)
        svc = ShadowService(
            id=1, name="Ollama", url="http://localhost:11434",
            service_type="self-hosted-llm", risk="critical",
            host="localhost", port=11434,
            discovered_by="port_scan",
            first_seen=now, last_seen=now,
            tags=["llm", "shadow"],
            metadata={"version": "0.1"},
        )
        assert svc.id == 1
        assert svc.risk == "critical"
        assert svc.metadata["version"] == "0.1"


# ---------------------------------------------------------------------------
# Shadow CRUD tests
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    """Create temp database for testing."""
    from agent_control_plane.inventory import get_connection
    os.environ["ACP_HOME"] = str(tmp_path)
    return get_connection()


class TestShadowCatalogCRUD:
    def test_upsert_and_list(self, conn):
        """Insert a shadow service and list it."""
        from agent_control_plane.inventory import list_shadow_services, upsert_shadow_service

        svc = ShadowService(
            name="Local Ollama", url="http://localhost:11434",
            service_type="self-hosted-llm", risk="critical",
            host="localhost", port=11434,
            discovered_by="port_scan",
        )
        svc_id = upsert_shadow_service(conn, svc)
        assert svc_id > 0

        services = list_shadow_services(conn)
        assert len(services) == 1
        assert services[0].name == "Local Ollama"

    def test_upsert_updates_existing(self, conn):
        """Upsert with same URL+type updates existing record."""
        from agent_control_plane.inventory import list_shadow_services, upsert_shadow_service

        svc1 = ShadowService(
            name="Test", url="http://localhost:8080",
            service_type="mcp-server", risk="high",
            host="localhost", port=8080,
            discovered_by="port_scan",
        )
        upsert_shadow_service(conn, svc1)

        svc2 = ShadowService(
            name="Test Updated", url="http://localhost:8080",
            service_type="mcp-server", risk="medium",
            host="localhost", port=8080,
            discovered_by="port_scan",
        )
        upsert_shadow_service(conn, svc2)

        services = list_shadow_services(conn)
        assert len(services) == 1
        assert services[0].name == "Test Updated"
        assert services[0].risk == "medium"

    def test_filter_by_risk(self, conn):
        """List can filter by risk level."""
        from agent_control_plane.inventory import list_shadow_services, upsert_shadow_service

        for risk in ("critical", "high", "medium"):
            upsert_shadow_service(conn, ShadowService(
                name=f"Test-{risk}", url=f"http://test-{risk}.local",
                service_type="unknown", risk=risk,
                host="localhost", port=8080,
                discovered_by="port_scan",
            ))

        critical = list_shadow_services(conn, risk="critical")
        assert len(critical) == 1

    def test_delete_shadow_service(self, conn):
        """Delete a shadow service."""
        from agent_control_plane.inventory import (
            delete_shadow_service,
            list_shadow_services,
            upsert_shadow_service,
        )

        svc_id = upsert_shadow_service(conn, ShadowService(
            name="ToDelete", url="http://delete.me",
            service_type="unknown", risk="low",
            host="localhost", port=1,
            discovered_by="port_scan",
        ))
        delete_shadow_service(conn, svc_id)

        services = list_shadow_services(conn)
        assert len(services) == 0

    def test_get_shadow_summary(self, conn):
        """Summary returns counts by risk and type."""
        from agent_control_plane.inventory import get_shadow_summary, upsert_shadow_service

        upsert_shadow_service(conn, ShadowService(
            name="S1", url="http://a",
            service_type="self-hosted-llm", risk="critical",
            host="h", port=1, discovered_by="port_scan",
        ))
        upsert_shadow_service(conn, ShadowService(
            name="S2", url="http://b",
            service_type="mcp-server", risk="high",
            host="h", port=2, discovered_by="port_scan",
        ))

        summary = get_shadow_summary(conn)
        assert summary["total"] == 2
        assert summary["by_risk"]["critical"] == 1
        assert summary["by_risk"]["high"] == 1
        assert summary["by_type"]["self-hosted-llm"] == 1


# ---------------------------------------------------------------------------
# Dashboard Shadow API tests
# ---------------------------------------------------------------------------


class TestShadowDashboardAPI:
    @pytest.fixture
    def client(self, tmp_path):
        os.environ["ACP_HOME"] = str(tmp_path)

        # Seed some shadow data
        from agent_control_plane.inventory import get_connection, upsert_shadow_service
        conn = get_connection()
        upsert_shadow_service(conn, ShadowService(
            name="API Test", url="http://test:11434",
            service_type="self-hosted-llm", risk="critical",
            host="test", port=11434, discovered_by="port_scan",
        ))
        conn.close()

        from fastapi.testclient import TestClient

        from agent_control_plane.dashboard import create_app
        return TestClient(create_app())

    def test_shadow_endpoint(self, client):
        """GET /api/shadow returns services."""
        res = client.get("/api/shadow")
        assert res.status_code == 200
        data = res.json()
        assert "services" in data
        assert len(data["services"]) >= 1

    def test_shadow_summary_endpoint(self, client):
        """GET /api/shadow/summary returns summary."""
        res = client.get("/api/shadow/summary")
        assert res.status_code == 200
        data = res.json()
        assert "summary" in data
        assert data["summary"]["total"] >= 1

    def test_shadow_page_renders(self, client):
        """GET /shadow returns HTML."""
        res = client.get("/shadow")
        assert res.status_code == 200
        assert "Shadow AI" in res.text


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestCLIShadowCommands:
    def test_cli_has_shadow_commands(self):
        """CLI parser recognizes shadow commands."""
        from agent_control_plane.cli import _build_parser
        parser = _build_parser()

        args = parser.parse_args(["shadow-scan", "--host", "127.0.0.1"])
        assert args.command == "shadow-scan"

        args = parser.parse_args(["shadow-list"])
        assert args.command == "shadow-list"

        args = parser.parse_args(["shadow-report"])
        assert args.command == "shadow-report"
