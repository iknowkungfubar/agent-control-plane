"""Discovery scanner — probes endpoints and identifies agent providers."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from typing import Any

import httpx

from agent_control_plane.inventory import get_connection, upsert_agent
from agent_control_plane.models import AgentEndpoint, AgentRecord, AgentStatus

# Cache for already-probed endpoints to avoid duplicate work
_probed_cache: set[str] = set()

# Known provider detection patterns
# Each entry: (path, status_code_expected, body_contains, provider_name)
PROVIDER_SIGNATURES: list[tuple[str, int | None, str | None, str]] = [
    ("/v1/models", 200, None, "openai"),
    ("/v1/chat/completions", 404, None, "openai"),
    ("/v1/messages", 404, None, "anthropic"),
    ("/api/tags", 200, None, "ollama"),
    ("/health", 200, "openai", "openai"),
    ("/mcp", 200, None, "mcp"),
    ("/health", 200, None, "custom"),
]


def _clear_cache() -> None:
    """Clear the probe cache (for testing)."""
    _probed_cache.clear()


def _make_name(host: str, port: int, provider: str) -> str:
    """Generate a stable agent name from host/port/provider."""
    safe_host = host.replace(".", "-").replace(":", "-")
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    return f"agent-{safe_host}-{port}-{ts}"


def _check_provider_by_response(
    url: str, status_code: int, body_text: str, headers: dict[str, str]
) -> str | None:
    """Identify provider from HTTP response characteristics.

    Checks response body for provider-specific patterns.
    Returns provider name or None if unknown.
    """
    body_lower = body_text.lower()

    # MCP servers often return JSON with "server" and "tools" keys
    if "server" in body_lower and "tools" in body_lower:
        try:
            data = json.loads(body_text)
            if "tools" in data:
                return "mcp"
        except (ValueError, json.JSONDecodeError):
            pass

    # OpenAI API returns model lists
    if status_code == 200 and "/v1" in url:
        if "data" in body_lower and ("gpt" in body_lower or "model" in body_lower):
            return "openai"

    # Anthropic API signature
    if "anthropic" in headers.get("server", "").lower():
        return "anthropic"
    if "anthropic-version" in headers:
        return "anthropic"

    # Ollama
    if status_code == 200 and "/api/tags" in url:
        return "ollama"

    # Generic health check with "ok" status
    if status_code == 200 and url.endswith("/health"):
        try:
            data = json.loads(body_text)
            if data.get("status") == "ok" or "uptime" in data:
                return "custom"
        except (ValueError, json.JSONDecodeError):
            pass

    return None


def probe_endpoint(
    host: str,
    port: int,
    timeout: float = 3.0,
) -> dict[str, Any] | None:
    """Probe a single host:port for an AI agent endpoint.

    Makes HTTP requests to known paths, identifies the provider,
    and returns discovery info.

    Returns:
        Dict with name, url, provider, host, port, status, metadata
        or None if no agent found.
    """
    cache_key = f"{host}:{port}"
    if cache_key in _probed_cache:
        return None
    _probed_cache.add(cache_key)

    base_url = f"http://{host}:{port}"
    found_provider = None
    response_body = ""
    response_headers: dict[str, str] = {}

    # Try known paths
    for path, expected_status, body_needle, provider_hint in PROVIDER_SIGNATURES:
        url = f"{base_url}{path}"
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url, follow_redirects=False)
            response_body = resp.text
            response_headers = dict(resp.headers)

            # Check if this response matches expected patterns
            if expected_status is not None and resp.status_code != expected_status:
                continue
            if body_needle and body_needle not in resp.text.lower():
                continue

            # If this path is a specific provider match, use it
            if provider_hint != "custom":
                found_provider = provider_hint
                break

            # Otherwise, try to identify from response
            identified = _check_provider_by_response(url, resp.status_code, resp.text, dict(resp.headers))
            if identified:
                found_provider = identified
                break

        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
            continue
        except Exception:
            continue

    if found_provider is None and response_body:
        # Last resort: check if anything is running on this port
        found_provider = _check_provider_by_response(
            base_url, 200, response_body, response_headers
        )

    if found_provider is None:
        return None

    return {
        "name": _make_name(host, port, found_provider),
        "url": base_url,
        "provider": found_provider,
        "host": host,
        "port": port,
        "status": "online",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "discovered_by": "port_scan",
            "headers": response_headers,
        },
    }


def scan_ports(
    host: str,
    ports: list[int],
    timeout: float = 2.0,
    max_workers: int = 20,
) -> list[dict[str, Any]]:
    """Scan a list of ports on a host for agent endpoints.

    Args:
        host: Target hostname/IP.
        ports: List of ports to scan.
        timeout: HTTP probe timeout.
        max_workers: Max parallel probes.

    Returns:
        List of discovery result dicts.
    """
    results: list[dict[str, Any]] = []
    for port in ports:
        result = probe_endpoint(host, port, timeout)
        if result is not None:
            results.append(result)
    return results


def register_discovered(info: dict[str, Any]) -> AgentRecord:
    """Register a discovered agent into the inventory database.

    Args:
        info: Discovery result dict from probe_endpoint().

    Returns:
        The created/updated AgentRecord.
    """
    now = datetime.now(timezone.utc)
    record = AgentRecord(
        name=info["name"],
        url=info["url"],
        provider=info.get("provider", "custom"),
        status=AgentStatus.ONLINE,
        tags=["discovered"],
        first_seen=now,
        last_seen=now,
    )
    conn = get_connection()
    upsert_agent(conn, record)
    conn.close()
    return record
