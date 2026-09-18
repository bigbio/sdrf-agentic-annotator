"""Execute the run matrix. Each run writes a self-describing directory; finished runs are skipped."""

from __future__ import annotations

import csv
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sdrf_model_bench import skills_arm
from sdrf_model_bench.config import ModelSpec, cost_usd
from sdrf_model_bench.evidence import estimate_tokens, evidence_dir, load_evidence
from sdrf_model_bench.prompts import build_messages
from sdrf_model_bench.providers import make_generate
from sdrf_model_bench.rawloop import run_raw
from sdrf_model_bench.validator import validate

OUTPUT_FALLBACK = 8192  # expected SDRF output tokens when the truth size is unknown
THINKING_ALLOWANCE = 16384  # extra output tokens for models that reason before answering
WORKERS = {"ollama": 1, "anthropic": 4, "claude-cli": 2, "openai": 4, "custom": 2, "claude-code": 2}


@dataclass(frozen=True)
class RunKey:
    model_id: str
    accession: str
    manuscript: bool
    replicate: int = 1

    @property
    def dirname(self) -> str:
        return f"{self.accession}__ms-{'on' if self.manuscript else 'off'}__r{self.replicate}"


@dataclass
class RunConfig:
    data_dir: Path
    outputs: Path
    pricing: dict
    validate_fn: Callable = validate
    generate_factory: Callable = make_generate
    plugin_dir: Path | None = None
    claude_bin: str = "claude"
    budget_tokens: int = 24000
    max_repairs: int = 2
    extra: dict = field(default_factory=dict)


def load_manifest(path: Path) -> list[dict]:
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def plan_runs(specs: list[ModelSpec], manifest: list[dict], replicates: dict[str, int] | None = None) -> list[RunKey]:
    replicates = replicates or {}
    return [RunKey(s.id, row["accession"], ms, r)
            for s in specs for row in manifest for ms in (True, False)
            for r in range(1, replicates.get(row["accession"], 1) + 1)]


def expected_output_tokens(data_dir: Path, accession: str) -> int:
    """Size of a correct answer, used only to flag context-limited runs (never shown to the model)."""
    truth = Path(data_dir) / "truth" / f"{accession}.sdrf.tsv"
    return int(estimate_tokens(truth.read_text()) * 1.2) if truth.exists() else OUTPUT_FALLBACK


def output_budget(data_dir: Path, accession: str) -> int:
    """Per-run output cap, identical for every raw model: twice a correct answer, at least 4096."""
    return max(4096, 2 * expected_output_tokens(data_dir, accession))


def _write(run_dir: Path, sdrf: str | None, record: dict) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    if sdrf:
        (run_dir / "sdrf.tsv").write_text(sdrf)
    (run_dir / "usage.json").write_text(json.dumps(record, indent=1))
    return record


def execute_run(key: RunKey, spec: ModelSpec, cfg: RunConfig) -> dict:
    run_dir = Path(cfg.outputs) / spec.id / key.dirname
    if (run_dir / "usage.json").exists():
        return json.loads((run_dir / "usage.json").read_text())
    ev = load_evidence(cfg.data_dir, key.accession)
    templates = ev.meta.get("templates") or []
    base = {"model_id": spec.id, "provider": spec.provider, "model": spec.model, "arm": spec.arm,
            "context_window": spec.context_window, "flags": []}
    try:
        if spec.arm == "raw":
            messages, info = build_messages(ev, key.manuscript, cfg.budget_tokens)
            if spec.context_window and info["prompt_tokens"] + expected_output_tokens(cfg.data_dir, key.accession) \
                    > spec.context_window:
                base["flags"].append("context_limited")
            budget = output_budget(cfg.data_dir, key.accession)
            generate = cfg.generate_factory(spec)
            res = run_raw(lambda m: generate(m, max_output_tokens=budget, thinking_tokens=THINKING_ALLOWANCE),
                          messages, run_dir,
                          lambda p: cfg.validate_fn(p, templates), cfg.max_repairs)
            (run_dir / "transcript.json").write_text(json.dumps(res.transcript, indent=1))
            record = {**base, **info, "max_output_tokens": budget, "thinking_tokens": THINKING_ALLOWANCE,
                      "usage": res.usage, "turns": res.turns, "wall_s": res.wall_s,
                      "stop_reasons": res.stop_reasons, "cost_usd": res.cost_usd if res.cost_usd is not None
                      else cost_usd(cfg.pricing, spec.model, res.usage)}
            if "refusal" in res.stop_reasons:
                record["flags"].append("refusal")
            sdrf = res.sdrf
        else:
            res = skills_arm.run_skills(spec.model, evidence_dir(cfg.data_dir, key.accession), key.accession,
                                        key.manuscript, templates, run_dir, cfg.plugin_dir, cfg.claude_bin)
            record = {**base, "usage": res["usage"], "turns": res["num_turns"], "wall_s": res["wall_s"],
                      "cost_usd": res["cost_usd"], "returncode": res["returncode"]}
            if res["leak_suspect"]:
                record["flags"].append("leak_suspect")
            if res.get("timed_out"):
                record["flags"].append("timeout")
            sdrf = res["sdrf"]
    except Exception as exc:
        # Crashes (API overload, network, OOM) are not scored and not cached: the next `run` retries them.
        record = {**base, "flags": ["error"], "error": repr(exc), "traceback": traceback.format_exc()}
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "error.json").write_text(json.dumps(record, indent=1))
        return record
    (run_dir / "error.json").unlink(missing_ok=True)
    if not sdrf:
        record["flags"].append("failed")
    return _write(run_dir, sdrf, record)


def run_matrix(specs: list[ModelSpec], keys: list[RunKey], cfg: RunConfig, log=print) -> list[dict]:
    by_id = {s.id: s for s in specs}
    groups: dict[str, list[RunKey]] = {}
    for k in keys:
        groups.setdefault(by_id[k.model_id].provider, []).append(k)
    results: list[dict] = []

    def run_group(provider: str, group: list[RunKey]):
        with ThreadPoolExecutor(max_workers=WORKERS.get(provider, 1)) as pool:
            for rec, k in zip(pool.map(lambda k: execute_run(k, by_id[k.model_id], cfg), group), group):
                log(f"{k.model_id:22s} {k.dirname:32s} flags={rec.get('flags')}")
                results.append(rec)

    with ThreadPoolExecutor(max_workers=len(groups) or 1) as outer:
        list(outer.map(lambda item: run_group(*item), groups.items()))
    return results
