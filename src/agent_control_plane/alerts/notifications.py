"""Alert notification backends — Slack, email, generic webhook formatters."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any


def format_slack(
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
    }
    color = colors.get(alert_type, "warning")
    emoji = {
        "DOWN": "🔴",
        "DEGRADED": "🟡",
        "RECOVERY": "✅",
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
            }
        ]
    }


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
    }.get(alert_type, "ℹ️")

    subject = f"{emoji} [ACP Alert] {alert_type} — {agent_name}"

    body = f"""
{'='*60}
AGENT CONTROL PLANE — ALERT
{'='*60}

Type:    {alert_type}
Agent:   {agent_name}
Status:  {status}
Time:    {__import__('datetime').datetime.now().isoformat()}

Message:
{message}

{'='*60}
This is an automated notification from Agent Control Plane.
"""

    return subject, body.strip()


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
) -> None:
    """Send an email via SMTP.

    Args:
        recipients: List of email addresses.
        subject: Email subject line.
        body: Plain text email body.
        smtp_host: SMTP server hostname.
        smtp_port: SMTP server port.
        smtp_user: Optional SMTP auth username.
        smtp_password: Optional SMTP auth password.
        from_addr: From address.
        use_tls: Use STARTTLS.
    """
    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    context = ssl.create_default_context() if use_tls else None

    with smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=15) as server:
        if use_tls:
            server.starttls(context=context)
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)
