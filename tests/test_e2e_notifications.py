"""E2E tests for the Notification Integration Hub (Sprint S-9).

Tests the full notification pipeline: sender formatting, routing to
multiple channels, history persistence, and CLI commands.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from agent_control_plane.models import AgentStatus

if TYPE_CHECKING:
    from collections.abc import Generator


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
    with tempfile.TemporaryDirectory(prefix="acp_notify_") as tmp:
        old_home = os.environ.get("ACP_HOME")
        old_cfg = os.environ.get("ACP_CONFIG")
        os.environ["ACP_HOME"] = tmp

        cfg = {
            "agents": [
                {
                    "name": "notify-agent",
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
                        "enabled": False,
                        "url": "http://localhost:0/placeholder",
                    },
                    "slack": {
                        "enabled": False,
                        "url": "",
                    },
                    "discord": {
                        "enabled": False,
                        "url": "",
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


class TestNotificationSenders:
    """Tests for individual notification channel formatters."""

    def test_discord_format_down(self):
        """Discord formatter produces a valid embed payload for DOWN alerts."""
        from agent_control_plane.notifications.senders import format_discord
        payload = format_discord(
            alert_type="DOWN",
            agent_name="discord-test",
            status="offline",
            message="Agent is unreachable",
        )
        assert "embeds" in payload
        assert len(payload["embeds"]) >= 1
        embed = payload["embeds"][0]
        assert embed["color"] == 0xFF0000  # Red for DOWN
        assert "discord-test" in str(embed)
        assert "offline" in str(embed)

    def test_discord_format_recovery(self):
        """Discord formatter returns green embed for RECOVERY alerts."""
        from agent_control_plane.notifications.senders import format_discord
        payload = format_discord(
            alert_type="RECOVERY",
            agent_name="recovery-test",
            status="online",
            message="Agent recovered",
        )
        assert payload["embeds"][0]["color"] == 0x00FF00  # Green

    def test_discord_format_degraded(self):
        """Discord formatter returns yellow embed for DEGRADED alerts."""
        from agent_control_plane.notifications.senders import format_discord
        payload = format_discord(
            alert_type="DEGRADED",
            agent_name="deg-test",
            status="degraded",
            message="Agent degraded",
        )
        assert payload["embeds"][0]["color"] == 0xFFFF00  # Yellow

    def test_slack_format_unchanged(self):
        """Slack formatter still works (existing contract)."""
        from agent_control_plane.notifications.senders import format_slack_blocks
        payload = format_slack_blocks(
            alert_type="DOWN",
            agent_name="slack-test",
            status="offline",
            message="Unreachable",
        )
        assert "attachments" in payload
        assert len(payload["attachments"]) >= 1

    def test_webhook_format(self):
        """Webhook sender builds correct JSON payload."""
        from agent_control_plane.notifications.senders import build_webhook_payload
        payload = build_webhook_payload(
            alert_type="DOWN",
            agent_name="webhook-test",
            status="offline",
            message="Connection refused",
        )
        assert payload["type"] == "DOWN"
        assert payload["agent_name"] == "webhook-test"
        assert payload["status"] == "offline"


class TestNotificationService:
    """Tests for the notification routing service."""

    def setup_method(self):
        """Clear webhook catcher before each test."""
        _WebhookCatcher.received.clear()

    def test_service_sends_to_all_enabled_channels(self, webhook_server: int):
        """Service sends notification to all enabled channels."""
        from agent_control_plane.notifications.service import send_notification

        _WebhookCatcher.received.clear()
        send_notification(
            alert_type="DOWN",
            agent_name="multi-test",
            status="offline",
            message="Multi-channel test",
            enabled_channels={
                "webhook": {"enabled": True, "url": f"http://127.0.0.1:{webhook_server}/alert"},
                "slack": {"enabled": False},
                "discord": {"enabled": False},
            },
        )
        time.sleep(0.3)
        assert len(_WebhookCatcher.received) >= 1
        assert _WebhookCatcher.received[0]["agent_name"] == "multi-test"

    def test_service_skips_disabled_channels(self):
        """Service does not send to disabled channels."""
        from agent_control_plane.notifications.service import send_notification

        result = send_notification(
            alert_type="DOWN",
            agent_name="skip-test",
            status="offline",
            message="Should skip",
            enabled_channels={
                "webhook": {"enabled": False},
                "slack": {"enabled": False},
                "discord": {"enabled": False},
            },
        )
        # Should return empty list (nothing sent)
        assert result == []

    def test_service_handles_invalid_webhook_url(self):
        """Service handles unreachable webhook URL gracefully."""
        from agent_control_plane.notifications.service import send_notification

        result = send_notification(
            alert_type="DOWN",
            agent_name="bad-host",
            status="offline",
            message="Bad host",
            enabled_channels={
                "webhook": {"enabled": True, "url": "http://192.0.2.1:1/webhook"},
            },
        )
        # Should return with error status
        assert len(result) >= 1
        assert result[0]["channel"] == "webhook"
        assert not result[0]["success"]

    def test_notification_history_recorded(self):
        """Send notification records delivery in notification_history."""
        from agent_control_plane.inventory import get_connection
        from agent_control_plane.notifications.service import send_notification

        send_notification(
            alert_type="DOWN",
            agent_name="history-test",
            status="offline",
            message="History test",
            enabled_channels={
                "webhook": {"enabled": True, "url": ""},
            },
        )
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM notification_history WHERE agent_name = ?",
            ("history-test",),
        ).fetchall()
        conn.close()
        assert len(rows) >= 1
        assert rows[0]["channel"] == "webhook"

    def test_cli_notify_list_works(self):
        """CLI notify list command shows notification history."""
        from agent_control_plane.notifications.service import send_notification

        send_notification(
            alert_type="DOWN",
            agent_name="cli-list-test",
            status="offline",
            message="CLI test",
            enabled_channels={
                "webhook": {"enabled": True, "url": ""},
            },
        )
        from agent_control_plane.cli import cmd_notify_list
        # Should not raise
        cmd_notify_list(limit=10)

    def test_notify_works_with_alert_engine(self, webhook_server: int):
        """Full integration: alert engine triggers notification service.

        Tests the wiring from evaluate_alerts -> dispatch_alerts -> send_notification.
        """
        from agent_control_plane.alerts.engine import (
            _reset_config_cache,
            _reset_state,
            dispatch_alerts,
            evaluate_alerts,
        )
        from agent_control_plane.inventory import get_connection, upsert_agent
        from agent_control_plane.models import AgentRecord

        _reset_state()
        _reset_config_cache()

        # Configure webhook in config
        cfg_path = Path(os.environ["ACP_CONFIG"])
        cfg = yaml.safe_load(cfg_path.read_text())
        cfg["alerts"]["channels"]["webhook"] = {
            "enabled": True,
            "url": f"http://127.0.0.1:{webhook_server}/alerts",
        }
        cfg_path.write_text(yaml.dump(cfg))
        _reset_config_cache()

        # Seed agent
        conn = get_connection()
        upsert_agent(conn, AgentRecord(
            name="integration-agent",
            url="http://localhost:9999",
            provider="custom",
            status=AgentStatus.ONLINE,
        ))
        conn.close()

        _WebhookCatcher.received.clear()

        # Trigger alert
        evaluate_alerts("integration-agent", AgentStatus.OFFLINE)
        alerts = evaluate_alerts("integration-agent", AgentStatus.OFFLINE)
        dispatch_alerts(alerts)
        time.sleep(0.3)

        # Verify webhook was called
        assert len(_WebhookCatcher.received) >= 1
        assert _WebhookCatcher.received[0]["agent_name"] == "integration-agent"

    def test_notify_test_sends_test_message(self, webhook_server: int):
        """CLI notify test sends a test notification."""
        from agent_control_plane.cli import cmd_notify_test

        # Should not raise
        cmd_notify_test(
            agent_name="test-agent",
            webhook_url=f"http://127.0.0.1:{webhook_server}/test",
        )
        time.sleep(0.3)
        assert len(_WebhookCatcher.received) >= 1
        assert _WebhookCatcher.received[0]["type"] == "TEST"
