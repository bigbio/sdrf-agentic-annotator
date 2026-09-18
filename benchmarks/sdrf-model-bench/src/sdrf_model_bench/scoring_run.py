"""Score every run directory under an outputs tree (ours or a collaborator's submission)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sdrf_model_bench.score import score_deterministic
from sdrf_model_bench.validator import validity_score

JUDGE_WEIGHT = 0.2
CONTAMINATION_THRESHOLD = 80.0


def parse_dirname(name: str) -> tuple[str, bool, int]:
    acc, ms, rep = name.split("__")
    return acc, ms == "ms-on", int(rep.lstrip("r"))


def score_run(run_dir: Path, data_dir: Path, validate_fn, judge_fn=None) -> dict:
    acc, manuscript, rep = parse_dirname(run_dir.name)
    usage = json.loads((run_dir / "usage.json").read_text()) if (run_dir / "usage.json").exists() else {}
    meta = json.loads((Path(data_dir) / "evidence" / acc / "meta.json").read_text())
    truth = (Path(data_dir) / "truth" / f"{acc}.sdrf.tsv").read_text()
    sdrf_path = run_dir / "sdrf.tsv"
    pred = sdrf_path.read_text() if sdrf_path.exists() else ""
    validation = validate_fn(sdrf_path, meta.get("templates") or []) if pred else None
    det = score_deterministic(truth, pred, validity_score(validation) if validation else 0.0)
    judged = judge_fn(truth, pred) if (judge_fn and pred) else None
    judge_score = judged["judge"] if judged else None
    headline = det["deterministic"] if judge_score is None else (
        (1 - JUDGE_WEIGHT) * det["deterministic"] + JUDGE_WEIGHT * judge_score)
    flags = list(usage.get("flags", []))
    if not pred and "failed" not in flags:
        flags.append("failed")
    if not manuscript and meta.get("tier") == "poor" and det["deterministic"] >= CONTAMINATION_THRESHOLD:
        flags.append("contamination_suspect")
    record = {
        "model_id": usage.get("model_id", run_dir.parent.name), "arm": usage.get("arm", "raw"),
        "model": usage.get("model", ""), "provider": usage.get("provider", ""), "think": usage.get("think", False),
        "accession": acc, "manuscript": manuscript, "replicate": rep,
        "qtype": meta.get("qtype"), "tier": meta.get("tier"), "pride_quality": meta.get("pride_quality"),
        **{k: v for k, v in det.items()},
        "judge": judge_score, "judge_detail": judged and {k: judged[k] for k in
                                                          ("factor_fidelity", "design_fidelity", "free_text")},
        "judge_usage": judged and judged["usage"],
        "headline": round(headline, 2),
        "n_errors": len(validation.errors) if validation else None,
        "usage": usage.get("usage", {}), "cost_usd": usage.get("cost_usd"), "wall_s": usage.get("wall_s"),
        "flags": flags,
    }
    (run_dir / "score.json").write_text(json.dumps(record, indent=1))
    return record


def score_tree(outputs: Path, data_dir: Path, validate_fn, judge_fn=None, rescore: bool = False) -> list[dict]:
    manifest = Path(data_dir) / "manifest.tsv"
    selected = {r["accession"] for r in csv.DictReader(open(manifest), delimiter="\t")} if manifest.exists() else None
    records = []
    for run_dir in sorted(Path(outputs).glob("*/*__ms-*__r*")):
        if selected is not None and parse_dirname(run_dir.name)[0] not in selected:
            continue  # dataset was replaced (e.g. its truth turned out to be machine-generated)
        if not (run_dir / "usage.json").exists():
            continue  # in progress, or crashed and awaiting retry: neither a success nor a model failure
        cached = run_dir / "score.json"
        if cached.exists() and not rescore:
            records.append(json.loads(cached.read_text()))
        else:
            records.append(score_run(run_dir, data_dir, validate_fn, judge_fn))
    return records
