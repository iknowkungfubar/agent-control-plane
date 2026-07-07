"""Alert rules configuration — loads alert config from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_control_plane.config import _resolve_config_path

_config_cache: dict[str, Any] = {}


def load_alert_config() -> dict[str, Any]:
    """Load alert configuration from the ACP config file.

    Returns:
        The alerts section of config, or default values.
    """
    cache_key = str(_resolve_config_path())
    if cache_key in _config_cache:
        return _config_cache[cache_key]

    defaults = {
        "enabled": True,
        "global": {
            "consecutive_failures": 3,
            "rate_limit_seconds": 300,
        },
        "channels": {
            "webhook": {"enabled": False, "url": ""},
            "slack": {"enabled": False, "url": ""},
            "email": {"enabled": False, "recipients": []},
        },
    }

    try:
        from agent_control_plane.config import load_config
        cfg = load_config()
        alerts_cfg = cfg.get("alerts", defaults)
        # Merge with defaults for missing keys
        result = dict(defaults)
        result.update(alerts_cfg)
        # Deep merge channels
        if "channels" in alerts_cfg:
            result["channels"] = dict(defaults["channels"])
            result["channels"].update(alerts_cfg["channels"])
        _config_cache[cache_key] = result
        return result
    except Exception:
        return dict(defaults)


def get_agent_alert_rules(agent_name: str) -> dict[str, Any]:
    """Get per-agent alert rules, or empty dict if none configured.

    Per-agent rules override global defaults:
    ```yaml
    agents:
      - name: my-agent
        alerts:
          consecutive_failures: 5
          rate_limit_seconds: 600
    ```
    """
    try:
        from agent_control_plane.config import load_config
        cfg = load_config()
        for agent in cfg.get("agents", []):
            if agent.get("name") == agent_name:
                return agent.get("alerts", {})
    except Exception:
        pass
    return {}
