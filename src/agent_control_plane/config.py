"""Configuration management for Agent Control Plane."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from agent_control_plane.models import AgentEndpoint


def _resolve_config_path() -> Path:
    """Resolve config file path: ACP_CONFIG env > ACP_HOME/config.yaml > ~/.acp/config.yaml."""
    if "ACP_CONFIG" in os.environ:
        return Path(os.environ["ACP_CONFIG"])

    home = _resolve_home()
    return home / "config.yaml"


def _resolve_home() -> Path:
    """Resolve data directory: ACP_HOME env > ~/.acp."""
    if "ACP_HOME" in os.environ:
        return Path(os.environ["ACP_HOME"])
    return Path.home() / ".acp"


def _resolve_db_path() -> Path:
    """Resolve the database file path."""
    return _resolve_home() / "inventory.db"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load agent configuration from YAML file.

    Args:
        path: Path to config file. If None, resolves automatically.

    Returns:
        Parsed configuration dict.

    Raises:
        FileNotFoundError: If config file does not exist.
        yaml.YAMLError: If config is invalid YAML.

    """
    if path is None:
        path = _resolve_config_path()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        return yaml.safe_load(f) or {}


def parse_agents(cfg: dict[str, Any]) -> list[AgentEndpoint]:
    """Parse agent list from configuration dict.

    Args:
        cfg: Configuration dict with optional "agents" key.

    Returns:
        List of configured agent endpoints.

    """
    agents: list[AgentEndpoint] = []
    for entry in cfg.get("agents", []):
        agents.append(
            AgentEndpoint(
                name=entry["name"],
                url=entry["url"],
                provider=entry.get("provider", "custom"),
                health_check_path=entry.get("health_check_path", "/health"),
                tags=entry.get("tags", []),
                metadata=entry.get("metadata", {}),
            ),
        )
    return agents


def get_home() -> Path:
    """Get the ACP home directory (creating it if needed)."""
    home = _resolve_home()
    home.mkdir(parents=True, exist_ok=True)
    return home


def get_db_path() -> Path:
    """Get database path."""
    return _resolve_db_path()
