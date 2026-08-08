"""Notification channel senders — formats and sends to webhook, Slack, Discord, email.

Each sender is a standalone function that takes alert fields and returns
a dict with 'success' and optionally 'error' keys.
"""

from __future__ import annotations

from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Webhook sender
# ---------------------------------------------------------------------------


def build_webhook_payload(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    """Build a generic JSON payload for webhook delivery.

    Returns a flat dict with standard alert fields.
    """
    return {
        "type": alert_type,
        "agent_name": agent_name,
        "status": status,
        "message": message,
        **_timestamp(),
        **extra,
    }


def send_webhook(
    url: str,
    payload: dict[str, Any],
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """POST a JSON payload to a webhook URL.

    Args:
        url: Target webhook URL.
        payload: JSON-serializable dict.
        timeout: HTTP timeout in seconds.
        headers: Optional custom headers.

    Returns:
        Dict with keys: success (bool), status_code (int or None),
        error (str or None).

    """
    if not url:
        return {"success": False, "status_code": None, "error": "No URL configured"}

    default_headers = {"Content-Type": "application/json"}
    if headers:
        default_headers.update(headers)

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=default_headers)
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "error": None}
    except httpx.TimeoutException:
        return {"success": False, "status_code": None, "error": "Request timed out"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "status_code": e.response.status_code, "error": str(e)}
    except httpx.RequestError as e:
        return {"success": False, "status_code": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Slack sender
# ---------------------------------------------------------------------------


def format_slack_blocks(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    """Format an alert as a Slack message with blocks.

    Returns a Slack-compatible payload dict.
    """
    colors = {
        "DOWN": "danger",
        "DEGRADED": "warning",
        "RECOVERY": "good",
        "DRIFT": "warning",
        "TEST": "good",
    }
    color = colors.get(alert_type, "warning")
    emoji = {
        "DOWN": "🔴",
        "DEGRADED": "🟡",
        "RECOVERY": "✅",
        "DRIFT": "🔧",
        "TEST": "🧪",
    }.get(alert_type, "ℹ️")

    title = f"{emoji} Agent {alert_type}: {agent_name}"

    return {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": message,
                "fields": [
                    {"title": "Agent", "value": agent_name, "short": True},
                    {"title": "Status", "value": status, "short": True},
                    {"title": "Type", "value": alert_type, "short": True},
                ],
                "footer": "Agent Control Plane",
                "ts": __import__("time").time(),
            },
        ],
    }


def send_slack(
    webhook_url: str,
    payload: dict[str, Any],
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST a Slack message to a Slack webhook URL.

    Args:
        webhook_url: Slack incoming webhook URL.
        payload: Slack message payload (from format_slack_blocks).
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with keys: success (bool), status_code (int or None),
        error (str or None).

    """
    if not webhook_url:
        return {"success": False, "status_code": None, "error": "No Slack webhook URL"}

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "error": None}
    except httpx.TimeoutException:
        return {"success": False, "status_code": None, "error": "Request timed out"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "status_code": e.response.status_code, "error": str(e)}
    except httpx.RequestError as e:
        return {"success": False, "status_code": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Discord sender
# ---------------------------------------------------------------------------


def format_discord(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    """Format an alert as a Discord embed message.

    Returns a Discord-compatible payload with embeds.
    """
    colors = {
        "DOWN": 0xFF0000,
        "DEGRADED": 0xFFFF00,
        "RECOVERY": 0x00FF00,
        "DRIFT": 0xFFA500,
        "TEST": 0x5865F2,
    }
    color = colors.get(alert_type, 0xFFFF00)

    emoji = {
        "DOWN": "🔴",
        "DEGRADED": "🟡",
        "RECOVERY": "✅",
        "DRIFT": "🔧",
        "TEST": "🧪",
    }.get(alert_type, "ℹ️")

    return {
        "embeds": [
            {
                "title": f"{emoji} Agent {alert_type}: {agent_name}",
                "description": message,
                "color": color,
                "fields": [
                    {"name": "Agent", "value": agent_name, "inline": True},
                    {"name": "Status", "value": status, "inline": True},
                    {"name": "Type", "value": alert_type, "inline": True},
                ],
                "footer": {"text": "Agent Control Plane"},
                "timestamp": __import__("datetime")
                .datetime.now(
                    __import__("datetime").timezone.utc,
                )
                .isoformat(),
            },
        ],
    }


def send_discord(
    webhook_url: str,
    payload: dict[str, Any],
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST a Discord embed message to a Discord webhook URL.

    Args:
        webhook_url: Discord webhook URL.
        payload: Discord message payload (from format_discord).
        timeout: HTTP timeout in seconds.

    Returns:
        Dict with keys: success (bool), status_code (int or None),
        error (str or None).

    """
    if not webhook_url:
        return {"success": False, "status_code": None, "error": "No Discord webhook URL"}

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return {"success": True, "status_code": resp.status_code, "error": None}
    except httpx.TimeoutException:
        return {"success": False, "status_code": None, "error": "Request timed out"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "status_code": e.response.status_code, "error": str(e)}
    except httpx.RequestError as e:
        return {"success": False, "status_code": None, "error": str(e)}


def format_email(
    alert_type: str,
    agent_name: str,
    status: str,
    message: str,
) -> tuple[str, str]:
    """Format an alert as email subject and body.

    Returns:
        Tuple of (subject, body_text).

    """
    emoji = {
        "DOWN": "🔴",
        "DEGRADED": "🟡",
        "RECOVERY": "✅",
        "DRIFT": "🔧",
        "TEST": "🧪",
    }.get(alert_type, "ℹ️")

    subject = f"{emoji} [ACP Alert] {alert_type} — {agent_name}"

    from datetime import UTC, datetime

    body = f"""
{"=" * 60}
AGENT CONTROL PLANE — ALERT
{"=" * 60}

Type:    {alert_type}
Agent:   {agent_name}
Status:  {status}
Time:    {datetime.now(UTC).isoformat()}

Message:
{message}

{"=" * 60}
This is an automated notification from Agent Control Plane.
"""

    return subject, body.strip()


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------


def send_email(
    recipients: list[str],
    subject: str,
    body: str,
    smtp_host: str = "localhost",
    smtp_port: int = 25,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
    from_addr: str = "acp@localhost",
    use_tls: bool = False,
    smtp_class: Any | None = None,
) -> dict[str, Any]:
    """Send an alert email via SMTP.

    Args:
        recipients: List of recipient email addresses. A single recipient
            may be passed as a plain string.
        subject: Email subject line.
        body: Plain-text email body.
        smtp_host: SMTP server hostname.
        smtp_port: SMTP server port.
        smtp_user: Optional SMTP auth username.
        smtp_password: Optional SMTP auth password.
        from_addr: From address.
        use_tls: Use STARTTLS.
        smtp_class: Inject a fake SMTP client class for testing.

    Returns:
        Dict with keys: success (bool), status_code (None for email),
        error (str or None).

    """
    if not recipients:
        return {"success": False, "status_code": None, "error": "No recipients configured"}

    if isinstance(recipients, str):
        recipients = [recipients]

    if not isinstance(recipients, (list, tuple)) or not all(
        isinstance(r, str) and r.strip() for r in recipients
    ):
        return {
            "success": False,
            "status_code": None,
            "error": "Invalid recipient address in configuration",
        }

    try:
        smtp_port = int(smtp_port)
    except (TypeError, ValueError):
        return {"success": False, "status_code": None, "error": f"Invalid SMTP port: {smtp_port!r}"}

    import smtplib
    import ssl
    from email.message import EmailMessage

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(recipients)

        client_cls = smtp_class or smtplib.SMTP
        context = ssl.create_default_context() if use_tls else None

        with client_cls(host=smtp_host, port=smtp_port, timeout=15) as server:
            if use_tls:
                server.starttls(context=context)
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return {"success": True, "status_code": None, "error": None}
    except (OSError, smtplib.SMTPException, TypeError, ValueError) as e:
        return {"success": False, "status_code": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp() -> dict[str, str]:
    """Return current UTC timestamp as ISO string."""
    from datetime import UTC, datetime

    return {"timestamp": datetime.now(UTC).isoformat()}
