"""Unit tests for cost tracking module."""

from __future__ import annotations

import pytest

from agent_control_plane.cost_tracker import estimate_monthly_cost, PROVIDER_COST_PER_1K_IN, PROVIDER_COST_PER_1K_OUT


class TestCostEstimation:
    """Test cost estimation logic."""

    def test_estimate_openai_cost(self):
        """OpenAI cost calculation is reasonable."""
        record = estimate_monthly_cost("test-agent", "openai", 1000000, 200000)
        assert record.estimated_tokens_in == 1000000
        assert record.estimated_tokens_out == 200000
        # (1M/1000 * 0.0025) + (200K/1000 * 0.010) = 2.50 + 2.00 = 4.50
        assert record.estimated_cost_usd == 4.50
        assert record.month is not None

    def test_estimate_anthropic_cost(self):
        """Anthropic cost calculation."""
        record = estimate_monthly_cost("a", "anthropic", 500000, 100000)
        # (500K/1000 * 0.003) + (100K/1000 * 0.015) = 1.50 + 1.50 = 3.00
        assert record.estimated_cost_usd == 3.00

    def test_local_models_free(self):
        """Local models (ollama, lm-studio) have zero cost."""
        for provider in ["ollama", "lm-studio"]:
            record = estimate_monthly_cost("local", provider, 999999, 999999)
            assert record.estimated_cost_usd == 0.0

    def test_custom_provider_default(self):
        """Custom provider uses default cost rates."""
        record = estimate_monthly_cost("custom", "custom", 100000, 50000)
        assert record.estimated_cost_usd > 0

    def test_provider_rate_tables(self):
        """All known providers have rate entries."""
        known = {"openai", "anthropic", "google", "mistral", "ollama", "lm-studio", "opencode", "custom"}
        for p in known:
            assert p in PROVIDER_COST_PER_1K_IN
            assert p in PROVIDER_COST_PER_1K_OUT
