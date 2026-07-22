"""Shadow AI / SaaS discovery scanner.

Extends ACP's discovery engine to scan network ranges, match services
against the fingerprint database, classify risk, and build a shadow IT
inventory catalog.
"""

from __future__ import annotations

import ipaddress
import socket
from datetime import UTC, datetime
from typing import Any

import httpx

from agent_control_plane.fingerprints import (
    FINGERPRINT_DB,
    classify_risk,
    get_all_ports,
    match_fingerprint,
)
from agent_control_plane.inventory import (
    get_connection,
    upsert_shadow_service,
)
from agent_control_plane.models import ShadowRisk, ShadowService


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Quick TCP connect check to see if a port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def probe_service(
    host: str,
    port: int,
    timeout: float = 3.0,
) -> dict[str, Any] | None:
    """Probe a host:port and match it against the fingerprint database.

    Returns a dict with service info, or None if no match.
    """
    base_url = f"http://{host}:{port}"

    # Build deduplicated list of paths to try
    paths_to_try: list[str] = ["/", "/health", "/status"]

    # Add paths from fingerprints that match this port
    for fp in FINGERPRINT_DB:
        if port in fp["port_hints"]:
            paths_to_try.extend(fp["paths"])

    paths_to_try = list(dict.fromkeys(paths_to_try))  # Dedupe preserving order

    last_body = ""
    last_status = 0

    for path in paths_to_try:
        url = f"{base_url}{path}"
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, follow_redirects=False)
            last_body = resp.text
            dict(resp.headers)
            last_status = resp.status_code

            # Try to match
            match = match_fingerprint(url, resp.status_code, resp.text, dict(resp.headers), port)
            if match:
                return {
                    "name": match["name"],
                    "url": base_url,
                    "service_type": match["category"].value,
                    "risk": match["risk"].value,
                    "host": host,
                    "port": port,
                    "discovered_by": "port_scan",
                    "fingerprint": match["description"],
                    "status_code": resp.status_code,
                    "body_preview": resp.text[:200],
                }
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
            continue
        except Exception:
            continue

    # No fingerprint match, but something responded
    if last_status > 0:
        return {
            "name": f"Unknown Service ({host}:{port})",
            "url": base_url,
            "service_type": "unknown",
            "risk": "unknown",
            "host": host,
            "port": port,
            "discovered_by": "port_scan",
            "fingerprint": "Unidentified service",
            "status_code": last_status,
            "body_preview": last_body[:200],
        }

    return None


def scan_cidr(
    cidr: str,
    ports: list[int] | None = None,
    timeout: float = 2.0,
    max_hosts: int = 256,
    max_workers: int = 20,
) -> list[dict[str, Any]]:
    """Scan a CIDR network range for shadow IT services.

    Args:
        cidr: CIDR notation (e.g. "10.0.0.0/24")
        ports: List of ports to scan. Defaults to all known ports.
        timeout: Per-probe timeout.
        max_hosts: Maximum hosts to scan (default 256 = /24).
        max_workers: Ignored (sequential for simplicity).

    Returns:
        List of discovery result dicts.

    """
    if ports is None:
        ports = sorted(get_all_ports())

    network = ipaddress.ip_network(cidr, strict=False)
    results: list[dict[str, Any]] = []
    hosts_scanned = 0

    for host in network.hosts():
        if hosts_scanned >= max_hosts:
            break
        host_str = str(host)
        hosts_scanned += 1

        # Quick TCP pre-check on common ports
        open_ports: list[int] = []
        for port in ports[:20]:  # Check top 20 ports first
            if _is_port_open(host_str, port, timeout=timeout * 0.5):
                open_ports.append(port)

        # Deep probe on open ports
        for port in open_ports:
            result = probe_service(host_str, port, timeout=timeout)
            if result:
                results.append(result)

    return results


def scan_host(
    host: str,
    ports: list[int] | None = None,
    timeout: float = 2.0,
) -> list[dict[str, Any]]:
    """Scan a single host for shadow IT services on given ports.

    Args:
        host: Hostname or IP.
        ports: Ports to scan. Defaults to all known ports.
        timeout: Per-probe timeout.

    Returns:
        List of discovery result dicts.

    """
    if ports is None:
        ports = sorted(get_all_ports())

    results: list[dict[str, Any]] = []
    for port in ports:
        result = probe_service(host, port, timeout=timeout)
        if result:
            results.append(result)
    return results


def register_shadow_discovery(results: list[dict[str, Any]]) -> int:
    """Register discovered shadow services into the catalog.

    Args:
        results: List of discovery result dicts from scan functions.

    Returns:
        Number of new records created.

    """
    conn = get_connection()
    now = datetime.now(UTC)
    count = 0

    for r in results:
        svc = ShadowService(
            name=r.get("name", "Unknown"),
            url=r.get("url", ""),
            service_type=r.get("service_type", "unknown"),
            risk=r.get("risk", "unknown"),
            host=r.get("host", ""),
            port=r.get("port", 0),
            discovered_by=r.get("discovered_by", "port_scan"),
            first_seen=now,
            last_seen=now,
            tags=[],
            metadata={
                "fingerprint": r.get("fingerprint", ""),
                "status_code": str(r.get("status_code", "")),
                "body_preview": r.get("body_preview", "")[:500],
            },
        )
        upsert_shadow_service(conn, svc)
        count += 1

    conn.close()
    return count


def classify_risk_for_result(result: dict[str, Any]) -> str:
    """Determine risk level for a discovered service."""
    service_type = result.get("service_type", "unknown")
    result.get("name", "")
    status_code = result.get("status_code", 0)

    # Services responding with 200 on unknown ports are HIGH risk
    if service_type == "unknown" and status_code in (200, 201):
        return ShadowRisk.HIGH.value

    # Default based on fingerprint risk
    risk = result.get("risk", "unknown")
    if risk and risk != "unknown":
        return risk

    return classify_risk(service_type, auth_required=False)
