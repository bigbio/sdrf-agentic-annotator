from pathlib import Path

import pytest

from sdrf_model_bench.config import cost_usd, load_models, load_pricing

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_roster_loads_and_is_consistent():
    specs = load_models(ROOT / "models.yaml")
    ids = [s.id for s in specs]
    assert len(ids) == len(set(ids))
    assert {s.arm for s in specs} == {"raw", "skills"}
    assert all(s.provider == "claude-code" for s in specs if s.arm == "skills")
    assert all("num_ctx" in s.options for s in specs if s.provider == "ollama")


def test_skills_arm_requires_claude_code(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("models:\n  - {id: x, provider: anthropic, model: m, arm: skills}\n")
    with pytest.raises(ValueError, match="skills arm"):
        load_models(p)


def test_cost_uses_cache_multipliers():
    pricing = {"m": {"input": 2.0, "output": 10.0}}
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000}
    assert cost_usd(pricing, "m", usage) == pytest.approx(2.0 + 1.0 + 0.2 + 2.5)
    assert cost_usd(pricing, "unknown", usage) is None


def test_shipped_pricing_covers_claude_roster():
    pricing = load_pricing(ROOT / "pricing.yaml")
    for s in load_models(ROOT / "models.yaml"):
        if s.provider in ("anthropic", "claude-code"):
            assert s.model in pricing
