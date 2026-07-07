"""Export functionality — CSV and JSON export of agent inventory."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_control_plane.inventory import (
    get_connection,
    get_summary_stats,
    list_agents,
    list_cost_records,
)


def build_export_data(db_path: Path | None = None) -> dict[str, Any]:
    """Build a complete export data structure.

    Args:
        db_path: Optional explicit database path.

    Returns:
        Dict with agents, cost_records, summary, and export timestamp.

    """
    conn = get_connection(db_path)
    agents = list_agents(conn)
    costs = list_cost_records(conn)
    summary = get_summary_stats(conn)
    conn.close()

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total_agents": summary.total_agents,
            "online": summary.online,
            "offline": summary.offline,
            "degraded": summary.degraded,
            "unknown": summary.unknown,
            "total_estimated_cost_monthly_usd": summary.total_estimated_cost_monthly_usd,
            "total_checks_run": summary.total_checks_run,
        },
        "agents": [
            {
                "name": a.name,
                "url": a.url,
                "provider": a.provider,
                "status": a.status.value,
                "tags": a.tags,
                "first_seen": a.first_seen.isoformat(),
                "last_seen": a.last_seen.isoformat(),
                "total_checks": a.total_checks,
                "successful_checks": a.successful_checks,
                "avg_response_time_ms": round(a.avg_response_time_ms, 2),
            }
            for a in agents
        ],
        "costs": [
            {
                "agent_name": c.agent_name,
                "month": c.month,
                "estimated_tokens_in": c.estimated_tokens_in,
                "estimated_tokens_out": c.estimated_tokens_out,
                "estimated_cost_usd": c.estimated_cost_usd,
            }
            for c in costs
        ],
    }


def export_json(output_path: Path, db_path: Path | None = None) -> Path:
    """Export inventory to JSON file.

    Args:
        output_path: Path for the JSON output.
        db_path: Optional explicit database path.

    Returns:
        Path to the written file.

    """
    data = build_export_data(db_path=db_path)
    output_path.write_text(json.dumps(data, indent=2))
    return output_path


def export_csv(output_path: Path) -> Path:
    """Export agent inventory to CSV file.

    Args:
        output_path: Path for the CSV output.

    Returns:
        Path to the written file.

    """
    data = build_export_data()

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "url", "provider", "status", "tags",
                         "first_seen", "last_seen", "total_checks",
                         "successful_checks", "avg_response_time_ms"])
        for agent in data["agents"]:
            writer.writerow([
                agent["name"],
                agent["url"],
                agent["provider"],
                agent["status"],
                ";".join(agent["tags"]),
                agent["first_seen"],
                agent["last_seen"],
                agent["total_checks"],
                agent["successful_checks"],
                agent["avg_response_time_ms"],
            ])

    return output_path
