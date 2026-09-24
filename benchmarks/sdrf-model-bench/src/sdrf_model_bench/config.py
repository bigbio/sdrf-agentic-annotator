"""Roster and price-table loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ARMS = ("raw", "skills")
PROVIDERS = ("anthropic", "claude-cli", "ollama", "openai", "claude-code", "custom")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    model: str
    arm: str
    context_window: int | None = None
    options: dict = field(default_factory=dict)
    enabled: bool = True


def load_models(path: Path, include_disabled: bool = False) -> list[ModelSpec]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    specs: list[ModelSpec] = []
    seen: set[str] = set()
    for raw in data.get("models", []):
        spec = ModelSpec(
            id=raw["id"],
            provider=raw["provider"],
            model=raw.get("model", ""),
            arm=raw.get("arm", "raw"),
            context_window=raw.get("context_window"),
            options=dict(raw.get("options") or {}),
            enabled=raw.get("enabled", True),
        )
        if spec.provider not in PROVIDERS:
            raise ValueError(f"{spec.id}: unknown provider {spec.provider!r} (known: {PROVIDERS})")
        if spec.arm not in ARMS:
            raise ValueError(f"{spec.id}: unknown arm {spec.arm!r} (known: {ARMS})")
        if spec.arm == "skills" and spec.provider != "claude-code":
            raise ValueError(f"{spec.id}: the skills arm requires provider 'claude-code'")
        if spec.id in seen:
            raise ValueError(f"duplicate model id {spec.id!r}")
        seen.add(spec.id)
        if spec.enabled or include_disabled:
            specs.append(spec)
    return specs


def load_pricing(path: Path) -> dict[str, dict[str, float]]:
    return (yaml.safe_load(Path(path).read_text()) or {}).get("models", {})


def cost_usd(pricing: dict, model: str, usage: dict) -> float | None:
    """API cost of one run in USD, or None when the model has no price (local models)."""
    p = pricing.get(model)
    if not p:
        return None
    per_in = p["input"] / 1e6
    return (
        usage.get("input_tokens", 0) * per_in
        + usage.get("output_tokens", 0) * p["output"] / 1e6
        + usage.get("cache_read_input_tokens", 0) * per_in * p.get("cache_read_multiplier", 0.1)
        + usage.get("cache_creation_input_tokens", 0) * per_in * p.get("cache_write_multiplier", 1.25)
    )
