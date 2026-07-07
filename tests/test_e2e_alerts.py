"""E2E tests for the alert and notification system.

Tests the full alert lifecycle: status transitions trigger alerts,
notifications are dispatched, deduplication prevents storms,
and history is persisted.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

from agent_control_plane.models import AgentStatus


class _WebhookCatcher(BaseHTTPRequestHandler):
    """Captures incoming webhook POSTs for test verification."""

    received: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        self.__class__.received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def webhook_server() -> Generator[int, None, None]:
    """Start a webhook catcher server on a free port."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    _WebhookCatcher.received = []
    server = HTTPServer(("127.0.0.1", port), _WebhookCatcher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield port
    server.shutdown()


@pytest.fixture(autouse=True)
def _temp_env():
    """Set up temp ACP_HOME for each test."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="acp_alerts_") as tmp:
        old_home = os.environ.get("ACP_HOME")
        old_cfg = os.environ.get("ACP_CONFIG")
        os.environ["ACP_HOME"] = tmp

        # Write config
        cfg = {
            "agents": [
                {
                    "name": "monitored-agent",
                    "url": "http://localhost:9999",
                    "provider": "custom",
                    "tags": ["production"],
                },
            ],
            "alerts": {
                "enabled": True,
                "global": {
                    "consecutive_failures": 2,
                    "rate_limit_seconds": 300,
                },
                "channels": {
                    "webhook": {
                        "enabled": True,
                        "url": "http://localhost:0/placeholder",
                    },
                },
            },
        }
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


class TestAlertEngine:
    """Test the alert engine detects transitions and fires notifications."""

    def setup_method(self, method):
        """Reset alert state before each test."""
        from agent_control_plane.alerts.engine import _reset_state
        _reset_state()

    def _configure_webhook(self, port: int):
        """Update config to point at the webhook catcher."""
        cfg_path = Path(os.environ["ACP_CONFIG"])
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["alerts"]["channels"]["webhook"]["url"] = f"http://127.0.0.1:{port}/alerts"
        cfg["alerts"]["channels"]["webhook"]["enabled"] = True
        cfg_path.write_text(yaml.dump(cfg))
        # Force reload
        from agent_control_plane.alerts.engine import _reset_config_cache
        _reset_config_cache()

    def _seed_agent(self, name: str = "monitored-agent", status: AgentStatus = AgentStatus.ONLINE):
        """Insert an agent record with a given status into inventory DB."""
        from agent_control_plane.inventory import get_connection, upsert_agent
        from agent_control_plane.models import AgentRecord
        conn = get_connection()
        upsert_agent(conn, AgentRecord(
            name=name,
            url="http://localhost:9999",
            provider="custom",
            status=status,
        ))
        conn.close()

    def test_transition_online_to_offline_triggers_alert(self):
        """Status transition online→offline generates a DOWN alert."""
        self._seed_agent("agent-a", AgentStatus.ONLINE)
        from agent_control_plane.alerts.engine import evaluate_alerts
        alerts = evaluate_alerts("agent-a", AgentStatus.OFFLINE)
        assert len(alerts) >= 1
        assert any(a["type"] == "DOWN" for a in alerts)

    def test_transition_online_to_degraded_triggers_alert(self):
        """Status transition online→degraded generates a DEGRADED alert."""
        self._seed_agent("agent-b", AgentStatus.ONLINE)
        from agent_control_plane.alerts.engine import evaluate_alerts
        alerts = evaluate_alerts("agent-b", AgentStatus.DEGRADED)
        assert len(alerts) >= 1
        assert any(a["type"] == "DEGRADED" for a in alerts)

    def test_recovery_offline_to_online_triggers_recovery(self):
        """Recovery offline→online generates a RECOVERY alert."""
        self._seed_agent("agent-c", AgentStatus.OFFLINE)
        from agent_control_plane.alerts.engine import evaluate_alerts
        alerts = evaluate_alerts("agent-c", AgentStatus.ONLINE)
        assert len(alerts) >= 1
        assert any(a["type"] == "RECOVERY" for a in alerts)

    def test_no_alert_on_same_status(self):
        """Same status transition produces no alert."""
        self._seed_agent("agent-d", AgentStatus.ONLINE)
        from agent_control_plane.alerts.engine import evaluate_alerts
        alerts = evaluate_alerts("agent-d", AgentStatus.ONLINE)
        assert len(alerts) == 0

    def test_consecutive_failure_threshold(self):
        """Consecutive failures beyond threshold trigger additional alerts."""
        self._seed_agent("agent-e", AgentStatus.ONLINE)
        from agent_control_plane.alerts.engine import evaluate_alerts
        # First failure: transition alert fires (online→offline)
        alerts1 = evaluate_alerts("agent-e", AgentStatus.OFFLINE)
        assert len(alerts1) >= 1
        assert alerts1[0]["type"] == "DOWN"
        # Second consecutive failure: should also fire (threshold=2 met)
        alerts2 = evaluate_alerts("agent-e", AgentStatus.OFFLINE)
        assert len(alerts2) >= 1

    def test_webhook_notification_dispatched(self, webhook_server: int):
        """Alert triggers a webhook POST to configured URL."""
        self._configure_webhook(webhook_server)
        self._seed_agent("agent-f", AgentStatus.ONLINE)
        from agent_control_plane.alerts.engine import dispatch_alerts, evaluate_alerts
        # Need 2 consecutive to trigger threshold
        evaluate_alerts("agent-f", AgentStatus.OFFLINE)
        alerts = evaluate_alerts("agent-f", AgentStatus.OFFLINE)
        _WebhookCatcher.received.clear()
        dispatch_alerts(alerts)
        time.sleep(0.5)
        assert len(_WebhookCatcher.received) >= 1
        payload = _WebhookCatcher.received[0]
        assert "type" in payload
        assert "agent_name" in payload

    def test_alert_history_persisted(self):
        """Dispatched alerts are stored in SQLite history."""
        self._seed_agent("agent-g", AgentStatus.ONLINE)
        from agent_control_plane.alerts.engine import dispatch_alerts, evaluate_alerts
        from agent_control_plane.alerts.history import get_alert_history
        # Trigger alerts
        evaluate_alerts("agent-g", AgentStatus.OFFLINE)
        alerts = evaluate_alerts("agent-g", AgentStatus.OFFLINE)
        dispatch_alerts(alerts)
        history = get_alert_history(limit=10)
        assert len(history) >= 1
        assert history[0]["agent_name"] == "agent-g"

    def test_deduplication_rate_limit(self):
        """Same alert type for same agent is rate-limited."""
        self._seed_agent("agent-h", AgentStatus.ONLINE)
        from agent_control_plane.alerts.engine import dispatch_alerts, evaluate_alerts
        from agent_control_plane.alerts.history import get_alert_history
        # Trigger first alert
        evaluate_alerts("agent-h", AgentStatus.OFFLINE)
        alerts1 = evaluate_alerts("agent-h", AgentStatus.OFFLINE)
        dispatch_alerts(alerts1)
        count1 = len(get_alert_history())
        # Immediately trigger same alert again (should be deduped)
        evaluate_alerts("agent-h", AgentStatus.OFFLINE)
        alerts2 = evaluate_alerts("agent-h", AgentStatus.OFFLINE)
        dispatch_alerts(alerts2)
        count2 = len(get_alert_history())
        # Count should be the same (didn't increase)
        assert count2 == count1, f"Expected no increase: {count1} → {count2}"

    def test_slack_notification_format(self):
        """Slack formatter produces valid Slack message attachments."""
        from agent_control_plane.alerts.notifications import format_slack
        msg = format_slack(
            alert_type="DOWN",
            agent_name="slack-test",
            status="offline",
            message="Agent is unreachable",
        )
        assert "attachments" in msg
        assert len(msg["attachments"]) >= 1
        assert "slack-test" in json.dumps(msg)

    def test_email_notification_format(self):
        """Email formatter produces valid email content."""
        from agent_control_plane.alerts.notifications import format_email
        subject, body = format_email(
            alert_type="DOWN",
            agent_name="email-test",
            status="offline",
            message="Connection refused",
        )
        assert "DOWN" in subject or "Alert" in subject
        assert "email-test" in body
