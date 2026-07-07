"""Health monitoring — ping agent endpoints and record results."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from agent_control_plane.inventory import (
    get_connection,
    get_agent,
    log_health_check,
    upsert_agent,
)
from agent_control_plane.models import AgentEndpoint, AgentRecord, AgentStatus


def check_agent_health(
    endpoint: AgentEndpoint,
    timeout: float = 5.0,
) -> tuple[AgentStatus, float, int | None, str | None]:
    """Ping a single agent endpoint and return health status.

    Args:
        endpoint: The agent endpoint to check.
        timeout: HTTP request timeout in seconds.

    Returns:
        Tuple of (status, response_time_ms, status_code, error_message).
    """
    start = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(endpoint.health_url)
        elapsed = (time.monotonic() - start) * 1000

        if response.status_code == 200:
            try:
                body = response.json()
                if body.get("status") == "ok":
                    return AgentStatus.ONLINE, elapsed, 200, None
                # Agent returned 200 but status isn't "ok" — degraded
                return AgentStatus.DEGRADED, elapsed, 200, f"unexpected status: {body.get('status')}"
            except (ValueError, KeyError):
                return AgentStatus.ONLINE, elapsed, 200, None
        elif 200 <= response.status_code < 500:
            return AgentStatus.DEGRADED, elapsed, response.status_code, f"HTTP {response.status_code}"
        else:
            return AgentStatus.OFFLINE, elapsed, response.status_code, f"HTTP {response.status_code}"

    except httpx.TimeoutException:
        return AgentStatus.OFFLINE, timeout * 1000, None, "timeout"
    except httpx.ConnectError:
        return AgentStatus.OFFLINE, 0, None, "connection refused"
    except httpx.RequestError as e:
        return AgentStatus.OFFLINE, 0, None, str(e)


def run_health_checks(
    agents: list[AgentEndpoint],
    timeout: float = 5.0,
) -> list[tuple[AgentEndpoint, AgentStatus, float, int | None, str | None]]:
    """Run health checks against all configured agents.

    Args:
        agents: List of agent endpoints to check.
        timeout: HTTP timeout per check.

    Returns:
        List of (endpoint, status, response_time_ms, status_code, error) tuples.
    """
    results: list[tuple[AgentEndpoint, AgentStatus, float, int | None, str | None]] = []
    conn = get_connection()

    for endpoint in agents:
        status, elapsed, status_code, error = check_agent_health(endpoint, timeout)

        # Log to health_log table
        log_health_check(
            conn,
            agent_name=endpoint.name,
            status=status,
            response_time_ms=elapsed,
            status_code=status_code,
            error=error,
        )

        # Evaluate alerts
        from agent_control_plane.alerts.engine import evaluate_alerts, dispatch_alerts
        alerts = evaluate_alerts(endpoint.name, status)
        if alerts:
            dispatch_alerts(alerts)

        # Update agent record
        existing = get_agent(conn, endpoint.name)
        if existing:
            updated = AgentRecord(
                name=existing.name,
                url=existing.url,
                provider=existing.provider,
                status=status,
                tags=existing.tags,
                first_seen=existing.first_seen,
                last_seen=datetime.now(timezone.utc),
                total_checks=existing.total_checks + 1,
                successful_checks=existing.successful_checks + (1 if status == AgentStatus.ONLINE else 0),
                avg_response_time_ms=_rolling_avg(existing.avg_response_time_ms, existing.total_checks, elapsed),
            )
            upsert_agent(conn, updated)

        results.append((endpoint, status, elapsed, status_code, error))

    conn.close()
    return results


def _rolling_avg(current_avg: float, count: int, new_value: float) -> float:
    """Update a running average with a new measurement."""
    if count == 0:
        return new_value
    return (current_avg * count + new_value) / (count + 1)
