"""Configuration drift detection engine.

Captures expected agent configurations as baselines, then compares
current agent state against those baselines to detect drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from sqlite3 import Connection

from agent_control_plane.inventory import (
    get_agent,
    get_config_baseline,
    get_connection,
    list_config_baselines,
    log_drift,
    upsert_config_baseline,
)
from agent_control_plane.models import (
    ConfigBaseline,
    DriftCheckResult,
    DriftRecord,
    DriftReport,
    DriftSeverity,
)


def _probe_agent_config(
    url: str,
    health_check_path: str = "/health",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Probe an agent endpoint to discover its current configuration.

    Args:
        url: Base URL of the agent.
        health_check_path: Path to health endpoint.
        timeout: HTTP timeout in seconds.

    Returns:
        Dict of discovered config fields (provider, version, etc.).

    """
    config: dict[str, Any] = {}
    base = url.rstrip("/")
    health_url = f"{base}/{health_check_path.lstrip('/')}"

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(health_url)
        if resp.status_code == 200:
            try:
                body = resp.json()
            except (ValueError, TypeError):
                body = {}
            config["status_code"] = 200
            config["response_body"] = body
            config["response_headers"] = dict(resp.headers)
        else:
            config["status_code"] = resp.status_code
    except (httpx.TimeoutException, httpx.ConnectError, httpx.RequestError) as e:
        config["error"] = str(e)

    # Try to probe /v1/models for OpenAI-compatible endpoints
    try:
        with httpx.Client(timeout=timeout) as client:
            models_resp = client.get(f"{base}/v1/models")
        if models_resp.status_code == 200:
            config["has_v1_models"] = True
            try:
                models_data = models_resp.json()
                model_ids = [m.get("id", "") for m in models_data.get("data", [])]
                if model_ids:
                    config["model_ids"] = model_ids
            except (ValueError, TypeError):
                pass
        else:
            config["has_v1_models"] = False
    except (httpx.TimeoutException, httpx.ConnectError, httpx.RequestError):
        config["has_v1_models"] = False

    return config


def _compare_field(
    agent_name: str,
    field: str,
    expected: str,
    actual: str,
) -> DriftCheckResult:
    """Compare a single config field and produce a drift check result.

    Args:
        agent_name: The agent being checked.
        field: The field name being compared.
        expected: The expected value from the baseline.
        actual: The actual value found.

    Returns:
        DriftCheckResult with severity assessment.

    """
    if expected == actual:
        return DriftCheckResult(
            agent_name=agent_name,
            field=field,
            expected=expected,
            actual=actual,
            severity=DriftSeverity.NONE,
            message=f"'{field}' matches baseline",
        )

    # Assess severity based on field type
    severity = DriftSeverity.MEDIUM
    message = f"'{field}' changed: '{expected}' -> '{actual}'"

    # Provider change is high severity
    if field == "provider":
        severity = DriftSeverity.HIGH
        message = f"Provider changed from '{expected}' to '{actual}'"

    # Health check path change is medium
    elif field == "health_check_path":
        severity = DriftSeverity.MEDIUM
        message = f"Health check path changed from '{expected}' to '{actual}'"

    # Version change is low (may be expected upgrade)
    elif field == "version":
        severity = DriftSeverity.LOW
        message = f"Version changed from '{expected}' to '{actual}'"

    return DriftCheckResult(
        agent_name=agent_name,
        field=field,
        expected=expected,
        actual=actual,
        severity=severity,
        message=message,
    )


def capture_baseline(agent_name: str, timeout: float = 5.0) -> ConfigBaseline | None:
    """Capture a configuration baseline from a live agent.

    Probes the agent's health endpoint and records expected values.

    Args:
        agent_name: Name of the agent to capture from.
        timeout: HTTP timeout in seconds.

    Returns:
        ConfigBaseline if successful, None if agent not found.

    """
    conn = get_connection()
    try:
        agent = get_agent(conn, agent_name)
        if agent is None:
            conn.close()
            return None

        baseline = ConfigBaseline(
            agent_name=agent.name,
            provider=str(getattr(agent, "provider", "custom")),
            health_check_path=agent.url.rstrip("/") + "/health",
            expected_tags=list(agent.tags),
            captured_by="auto",
        )

        # Probe for version info
        config = _probe_agent_config(agent.url, timeout=timeout)
        if "response_body" in config:
            body = config["response_body"]
            if isinstance(body, dict):
                version = body.get("version") or body.get("model") or body.get("service")
                if version:
                    baseline.expected_version = str(version)
                # Store extra info
                extra: dict[str, str] = {}
                for key in ("status", "uptime", "service", "environment"):
                    if key in body:
                        extra[key] = str(body[key])
                if extra:
                    baseline.additional_fields = extra

        upsert_config_baseline(conn, baseline)
        return baseline
    finally:
        conn.close()


def set_baseline(
    agent_name: str,
    provider: str | None = None,
    health_check_path: str | None = None,
    expected_version: str | None = None,
    expected_tags: list[str] | None = None,
    additional_fields: dict[str, str] | None = None,
    conn: Connection | None = None,
) -> ConfigBaseline | None:
    """Manually set a configuration baseline for an agent.

    Args:
        agent_name: Name of the agent.
        provider: Expected provider type.
        health_check_path: Expected health check path.
        expected_version: Expected version string.
        expected_tags: Expected tags.
        additional_fields: Additional expected fields.
        conn: Optional database connection (for testing). If not provided,
              a new connection is created.

    Returns:
        ConfigBaseline if agent exists, None otherwise.

    """
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        agent = get_agent(conn, agent_name)
        if agent is None:
            if close_conn:
                conn.close()
            return None

        existing = get_config_baseline(conn, agent_name)
        resolved_provider = provider if provider is not None else (
            existing.provider if existing else agent.provider
        )
        resolved_health_path = health_check_path if health_check_path is not None else (
            existing.health_check_path if existing else "/health"
        )
        resolved_version = expected_version if expected_version is not None else (
            existing.expected_version if existing else None
        )
        resolved_tags = expected_tags if expected_tags is not None else (
            existing.expected_tags if existing else list(agent.tags)
        )
        resolved_extra = additional_fields if additional_fields is not None else (
            existing.additional_fields if existing else {}
        )
        baseline = ConfigBaseline(
            agent_name=agent_name,
            provider=resolved_provider,
            health_check_path=resolved_health_path,
            expected_version=resolved_version,
            expected_tags=resolved_tags,
            additional_fields=resolved_extra,
            captured_by="manual",
        )
        upsert_config_baseline(conn, baseline)
        return baseline
    finally:
        if close_conn:
            conn.close()


def check_drift(agent_name: str, timeout: float = 5.0) -> DriftReport:
    """Check an agent's current config against its baseline.

    Args:
        agent_name: Name of the agent to check.
        timeout: HTTP timeout in seconds.

    Returns:
        DriftReport with all drift results.

    """
    conn = get_connection()
    try:
        agent = get_agent(conn, agent_name)
        if agent is None:
            conn.close()
            return DriftReport(
                agent_name=agent_name,
                has_baseline=False,
                drift_count=0,
                max_severity=DriftSeverity.NONE,
                results=[],
            )

        baseline = get_config_baseline(conn, agent_name)
        if baseline is None:
            conn.close()
            return DriftReport(
                agent_name=agent_name,
                has_baseline=False,
                drift_count=0,
                max_severity=DriftSeverity.NONE,
                results=[],
            )

        results: list[DriftCheckResult] = []

        # Compare provider
        current_provider = str(getattr(agent, "provider", ""))
        results.append(_compare_field(agent_name, "provider", baseline.provider, current_provider))

        # Compare tags (serialize to string for comparison)
        expected_tags_str = ", ".join(sorted(baseline.expected_tags)) if baseline.expected_tags else ""
        actual_tags_str = ", ".join(sorted(agent.tags)) if agent.tags else ""
        results.append(_compare_field(agent_name, "tags", expected_tags_str, actual_tags_str))

        # Probe current endpoint for additional comparisons
        probe_result = _probe_agent_config(agent.url, timeout=timeout)

        # Compare version if baseline has one
        if baseline.expected_version:
            discovered_version = ""
            if "response_body" in probe_result:
                body = probe_result["response_body"]
                if isinstance(body, dict):
                    discovered_version = str(body.get("version") or body.get("model") or body.get("service", ""))
            results.append(_compare_field(agent_name, "version", baseline.expected_version, discovered_version))

        # Compare health check availability
        if probe_result.get("error"):
            results.append(DriftCheckResult(
                agent_name=agent_name,
                field="reachability",
                expected="reachable",
                actual=f"unreachable: {probe_result['error']}",
                severity=DriftSeverity.CRITICAL,
                message=f"Agent '{agent_name}' is unreachable for config verification",
            ))

        # Compare additional fields from baseline
        for key, expected_val in baseline.additional_fields.items():
            actual_val = ""
            if "response_body" in probe_result:
                body = probe_result["response_body"]
                if isinstance(body, dict):
                    actual_val = str(body.get(key, ""))
            results.append(_compare_field(agent_name, f"additional.{key}", expected_val, actual_val))

        # Determine overall severity
        max_sev = DriftSeverity.NONE
        drift_count = 0
        for r in results:
            sev = DriftSeverity(r.severity) if isinstance(r.severity, str) else r.severity
            if sev != DriftSeverity.NONE:
                drift_count += 1
            if _severity_rank(sev) > _severity_rank(max_sev):
                max_sev = sev

        # Log drift events to database
        for r in results:
            if DriftSeverity(r.severity) != DriftSeverity.NONE:
                log_drift(conn, DriftRecord(
                    agent_name=r.agent_name,
                    field_name=r.field,
                    expected=r.expected,
                    actual=r.actual,
                    severity=r.severity,
                    message=r.message,
                    detected_at=r.checked_at,
                ))

        # Fire drift alert if drift detected
        if drift_count > 0:
            try:
                from agent_control_plane.alerts.engine import dispatch_drift_alert
                details = "; ".join(
                    r.message for r in results
                    if DriftSeverity(r.severity) != DriftSeverity.NONE
                )
                dispatch_drift_alert(
                    agent_name=agent_name,
                    drift_count=drift_count,
                    max_severity=max_sev.value,
                    details=details[:200],
                )
            except Exception:
                pass  # Alert dispatch failures should not break drift check

        conn.commit()
        return DriftReport(
            agent_name=agent_name,
            has_baseline=True,
            drift_count=drift_count,
            max_severity=max_sev,
            results=results,
        )
    finally:
        conn.close()


def check_all_drift(timeout: float = 5.0) -> list[DriftReport]:
    """Check all agents with baselines for configuration drift.

    Returns:
        List of DriftReport for each agent with a baseline.

    """
    conn = get_connection()
    try:
        baselines = list_config_baselines(conn)
    finally:
        conn.close()

    reports: list[DriftReport] = []
    for bl in baselines:
        report = check_drift(bl.agent_name, timeout=timeout)
        reports.append(report)
    return reports


def _severity_rank(severity: DriftSeverity) -> int:
    """Get numeric rank for a severity level."""
    ranks = {
        DriftSeverity.NONE: 0,
        DriftSeverity.LOW: 1,
        DriftSeverity.MEDIUM: 2,
        DriftSeverity.HIGH: 3,
        DriftSeverity.CRITICAL: 4,
    }
    return ranks.get(severity, 0)
