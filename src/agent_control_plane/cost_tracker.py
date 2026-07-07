"""Cost tracking — estimate and record AI agent costs."""

from __future__ import annotations

from datetime import datetime, timezone

from agent_control_plane.inventory import get_connection, list_cost_records, upsert_cost_record
from agent_control_plane.models import CostRecord


# Approximate cost per 1K tokens by provider ($USD)
PROVIDER_COST_PER_1K_IN = {
    "openai": 0.0025,
    "anthropic": 0.0030,
    "google": 0.0015,
    "mistral": 0.0020,
    "ollama": 0.0,  # Free (local)
    "lm-studio": 0.0,  # Free (local)
    "opencode": 0.0010,
    "custom": 0.0010,
}

PROVIDER_COST_PER_1K_OUT = {
    "openai": 0.010,
    "anthropic": 0.015,
    "google": 0.005,
    "mistral": 0.008,
    "ollama": 0.0,
    "lm-studio": 0.0,
    "opencode": 0.004,
    "custom": 0.004,
}


def estimate_monthly_cost(
    agent_name: str,
    provider: str,
    tokens_in: int,
    tokens_out: int,
) -> CostRecord:
    """Estimate monthly cost for an agent based on token usage.

    Args:
        agent_name: Name of the agent.
        provider: Provider name (openai, anthropic, etc.).
        tokens_in: Estimated tokens consumed (input/prompt) this month.
        tokens_out: Estimated tokens generated (output/completion) this month.

    Returns:
        CostRecord with estimated cost.
    """
    cost_in = (tokens_in / 1000) * PROVIDER_COST_PER_1K_IN.get(provider, 0.001)
    cost_out = (tokens_out / 1000) * PROVIDER_COST_PER_1K_OUT.get(provider, 0.004)
    now = datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")

    return CostRecord(
        agent_name=agent_name,
        month=month,
        estimated_tokens_in=tokens_in,
        estimated_tokens_out=tokens_out,
        estimated_cost_usd=round(cost_in + cost_out, 4),
        last_updated=now,
    )


def record_cost(agent_name: str, provider: str, tokens_in: int, tokens_out: int) -> CostRecord:
    """Calculate and persist a cost record.

    Args:
        agent_name: Name of the agent.
        provider: Provider name.
        tokens_in: Token input count.
        tokens_out: Token output count.

    Returns:
        The saved CostRecord.
    """
    record = estimate_monthly_cost(agent_name, provider, tokens_in, tokens_out)
    conn = get_connection()
    upsert_cost_record(conn, record)
    conn.close()
    return record


def get_all_costs() -> list[CostRecord]:
    """Get all cost records from the database.

    Returns:
        List of CostRecord objects.
    """
    conn = get_connection()
    records = list_cost_records(conn)
    conn.close()
    return records


def total_monthly_cost() -> float:
    """Get total estimated monthly cost across all agents.

    Returns:
        Total cost in USD.
    """
    records = get_all_costs()
    return round(sum(r.estimated_cost_usd for r in records), 2)
