import re

import pytest

from service.prices import Prices, cost_usd, load_prices, worst_case_usd

P = Prices("m", 1.0, 5.0, 1.25, 0.1, "https://example.test/pricing", "2026-10-05")


def test_committed_prices_are_for_the_live_model_with_a_source_and_date():
    p = load_prices("service/prices.json")
    assert p.model == "claude-haiku-4-5-20251001"
    assert p.source.startswith("https://") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.checked)
    assert 0 < p.cache_read < p.input < p.cache_write < p.output


def test_cost_counts_every_usage_field_and_treats_none_as_zero():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_creation_input_tokens": None,
             "cache_read_input_tokens": 200_000}
    assert cost_usd(P, usage) == pytest.approx(1.0 + 0.5 + 0.02)
    assert cost_usd(P, {}) == 0.0 and cost_usd(P, None) == 0.0


def test_worst_case_assumes_three_characters_a_token_and_the_full_output_cap():
    # 30,000 characters is at most 10,000 tokens in at $1, plus 4,000 tokens out at $5, per million
    assert worst_case_usd(P, 30_000, 4_000) == pytest.approx(0.03)
