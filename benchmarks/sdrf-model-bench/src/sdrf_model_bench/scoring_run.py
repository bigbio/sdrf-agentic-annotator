"""Score every run directory under an outputs tree (ours or a collaborator's submission)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from sdrf_model_bench.score import score_deterministic
from sdrf_model_bench.validator import ValidationResult, distinct_errors, validity_score

JUDGE_WEIGHT = 0.2
CONTAMINATION_THRESHOLD = 80.0


def parse_dirname(name: str) -> tuple[str, bool, int]:
    acc, ms, rep = name.split("__")
    return acc, ms == "ms-on", int(rep.lstrip("r"))


def score_run(run_dir: Path, data_dir: Path, validate_fn, judge_fn=None) -> dict:
    acc, manuscript, rep = parse_dirname(run_dir.name)
    usage = json.loads((run_dir / "usage.json").read_text()) if (run_dir / "usage.json").exists() else {}
    meta = json.loads((Path(data_dir) / "evidence" / acc / "meta.json").read_text())
    truth = (Path(data_dir) / "truth" / f"{acc}.reference.tsv").read_text()
    sdrf_path = run_dir / "sdrf.tsv"
    pred = sdrf_path.read_text() if sdrf_path.exists() else ""
    validation = validate_fn(sdrf_path, meta.get("templates") or []) if pred else None
    shared = 0
    if validation and validation.errors:
        validation, shared = drop_reference_errors(validation, data_dir, acc, meta, validate_fn)
    det = score_deterministic(truth, pred, validity_score(validation) if validation else 0.0)
    judged, judge_failed = None, False
    if judge_fn and pred:
        try:
            judged = judge_fn(truth, pred)
        except Exception:  # usage limit or CLI failure: score without the judge now, retry it next time
            judge_failed = True
    judge_score = judged["judge"] if judged else None
    headline = det["deterministic"] if judge_score is None else (
        (1 - JUDGE_WEIGHT) * det["deterministic"] + JUDGE_WEIGHT * judge_score)
    flags = list(usage.get("flags", []))
    if not pred and "failed" not in flags:
        flags.append("failed")
    if judge_failed:
        flags.append("judge_pending")
    if not manuscript and usage.get("provider") != "external" and meta.get("tier") == "poor" and det["deterministic"] >= CONTAMINATION_THRESHOLD:
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
        "reference_shared_errors": shared,
        "human_min": usage.get("human_min"),
        "usage": usage.get("usage", {}), "cost_usd": usage.get("cost_usd"), "wall_s": usage.get("wall_s"),
        "flags": flags,
    }
    if not judge_failed:
        (run_dir / "score.json").write_text(json.dumps(record, indent=1))
    return record


def reference_error_classes(data_dir: Path, acc: str, templates, validate_fn) -> set[str]:
    """The validator error classes the curated reference itself fails, cached next to the truth.

    A run that follows the curated convention should not lose validity for it: the SILAC
    references (e.g. PXD013923) repeat (source name, assay name) across the channels of a run,
    and parse_sdrf rejects exactly that in every file that copies the convention."""
    cache = Path(data_dir) / "truth" / f"{acc}.validation.json"
    if cache.exists():
        return set(json.loads(cache.read_text()))
    classes = distinct_errors(validate_fn(Path(data_dir) / "truth" / f"{acc}.reference.tsv", templates).errors)
    cache.write_text(json.dumps(classes, indent=1))
    return set(classes)


def drop_reference_errors(validation, data_dir: Path, acc: str, meta: dict, validate_fn):
    ref = reference_error_classes(data_dir, acc, meta.get("templates") or [], validate_fn)
    kept = [e for e in validation.errors if distinct_errors([e])[0] not in ref]
    return ValidationResult(errors=kept, warnings=validation.warnings, raw=validation.raw), \
        len(validation.errors) - len(kept)


def rescore_deterministic(run_dir: Path, data_dir: Path) -> dict | None:
    """Recompute the deterministic score from the saved SDRF and the reference, keeping the cached
    validity and judge. Seconds per tree instead of hours: no validator, no judge calls. Used to
    re-run a changed rubric over finished outputs; writes nothing."""
    cached_path = run_dir / "score.json"
    if not cached_path.exists():
        return None
    cached = json.loads(cached_path.read_text())
    acc = parse_dirname(run_dir.name)[0]
    truth = (Path(data_dir) / "truth" / f"{acc}.reference.tsv").read_text()
    sdrf_path = run_dir / "sdrf.tsv"
    pred = sdrf_path.read_text() if sdrf_path.exists() else ""
    det = score_deterministic(truth, pred, cached.get("validity") or 0.0)
    judge_score = cached.get("judge")
    headline = det["deterministic"] if judge_score is None else (
        (1 - JUDGE_WEIGHT) * det["deterministic"] + JUDGE_WEIGHT * judge_score)
    return {**cached, **det, "headline": round(headline, 2)}


def score_tree(outputs: Path, data_dir: Path, validate_fn, judge_fn=None, rescore: bool = False,
               deterministic_only: bool = False) -> list[dict]:
    manifest = Path(data_dir) / "manifest.tsv"
    selected = {r["accession"] for r in csv.DictReader(open(manifest), delimiter="\t")} if manifest.exists() else None
    records = []
    for run_dir in sorted(Path(outputs).glob("*/*__ms-*__r*")):
        if selected is not None and parse_dirname(run_dir.name)[0] not in selected:
            continue  # dataset was replaced (e.g. its truth turned out to be machine-generated)
        if not (run_dir / "usage.json").exists():
            continue  # in progress, or crashed and awaiting retry: neither a success nor a model failure
        cached = run_dir / "score.json"
        if deterministic_only:
            rec = rescore_deterministic(run_dir, data_dir)
            if rec is not None:
                records.append(rec)
            continue
        if cached.exists() and not rescore:
            records.append(json.loads(cached.read_text()))
        else:
            records.append(score_run(run_dir, data_dir, validate_fn, judge_fn))
    return records
