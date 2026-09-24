"""`sdrf-bench` command line: select -> freeze -> run -> score -> report, plus pack for hand-off."""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
import tarfile
from pathlib import Path

DEFAULT_PLUGIN = Path.home() / ".claude/plugins/marketplaces/sdrf-skills"
EXCLUDED_TEMPLATES = {"crosslinking"}  # a different experiment type, not a standard TMT/LFQ/DIA study
PACK_EXCLUDE = {"outputs", "results", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
MANIFEST_COLS = ["accession", "qtype", "tier", "pride_quality", "organism", "n_rows", "has_deposited_sdrf",
                 "pmcid", "license"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sdrf-bench", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("select", help="pick and freeze the benchmark datasets (maintainers only)")
    s.add_argument("--datasets", type=Path, help="sdrf-annotated-datasets/datasets directory")
    s.add_argument("--data", type=Path, default=Path("data"))
    s.add_argument("--seed", type=int, default=20260918)
    s.add_argument("--pool-per-type", type=int, default=12)
    s.add_argument("--per-type", type=int, default=4)
    s.add_argument("--plugin-src", type=Path, default=DEFAULT_PLUGIN)

    f = sub.add_parser("freeze", help="re-fetch evidence for the manifest (changes the benchmark!)")
    f.add_argument("--datasets", type=Path)
    f.add_argument("--data", type=Path, default=Path("data"))

    x = sub.add_parser("replace", help="swap selected datasets for the next eligible ones (same type and tier)")
    x.add_argument("--accessions", required=False, default="", help="comma-separated accessions to drop")
    x.add_argument("--reason", default="replaced")
    x.add_argument("--datasets", type=Path)
    x.add_argument("--data", type=Path, default=Path("data"))
    x.add_argument("--seed", type=int, default=20260918)
    x.add_argument("--plugin-src", type=Path, default=DEFAULT_PLUGIN)

    r = sub.add_parser("run", help="generate SDRFs for the roster")
    r.add_argument("--models", type=Path, default=Path("models.yaml"))
    r.add_argument("--pricing", type=Path, default=Path("pricing.yaml"))
    r.add_argument("--only", default="", help="comma-separated model ids (default: all enabled)")
    r.add_argument("--accessions", default="", help="comma-separated subset of the manifest")
    r.add_argument("--manuscript", choices=["both", "on", "off"], default="both")
    r.add_argument("--replicates", default="", help="e.g. PXD000001:3,PXD000002:3")
    r.add_argument("--data", type=Path, default=Path("data"))
    r.add_argument("--outputs", type=Path, default=Path("outputs"))
    r.add_argument("--plugin-src", type=Path, default=DEFAULT_PLUGIN)
    r.add_argument("--claude-bin", default=None)
    r.add_argument("--workers", type=int, default=None,
                   help="cap concurrent runs (1 = one run at a time, groups in sequence); default per provider")

    c = sub.add_parser("score", help="score an outputs tree (ours or a submission)")
    c.add_argument("--outputs", type=Path, default=Path("outputs"))
    c.add_argument("--data", type=Path, default=Path("data"))
    c.add_argument("--out", type=Path, default=Path("results/runs.jsonl"))
    c.add_argument("--judge-model", default="claude-sonnet-5")
    c.add_argument("--judge-provider", default="claude-cli", choices=["claude-cli", "anthropic"],
                   help="claude-cli uses your Claude Code login; anthropic needs ANTHROPIC_API_KEY")
    c.add_argument("--no-judge", action="store_true")
    c.add_argument("--rescore", action="store_true")
    c.add_argument("--deterministic-only", action="store_true",
                   help="recompute the deterministic score from saved outputs, keeping cached validity and judge")

    o = sub.add_parser("report", help="summary table, slide and backup plots")
    o.add_argument("--results", type=Path, nargs="+", default=[Path("results/runs.jsonl")],
                   help="one or more runs.jsonl, e.g. ours plus a collaborator's scored SDRFs")
    o.add_argument("--deterministic", action="store_true",
                   help="rank on the deterministic score alone (drop the judge), e.g. when mixing judged and unjudged runs")
    o.add_argument("--collaborators-only", action="store_true",
                   help="only the per-collaborator slides and figures (when configurations cover different datasets)")
    o.add_argument("--manuscript", choices=["both", "on", "off"], default="both",
                   help="keep only runs with (on) or without (off) the paper")
    o.add_argument("--out", type=Path, default=Path("results"))
    o.add_argument("--models", type=Path, default=Path("models.yaml"))
    o.add_argument("--data", type=Path, default=Path("data"),
                   help="frozen pack, used to draw the reads-no-evidence baseline")

    m = sub.add_parser("prompt", help="print the exact raw-arm messages for one run")
    m.add_argument("--accession", default="")
    m.add_argument("--manuscript", choices=["on", "off"], default="on")
    m.add_argument("--data", type=Path, default=Path("data"))

    k = sub.add_parser("pack", help="bundle code + frozen data for a collaborator")
    k.add_argument("--root", type=Path, default=Path("."))
    k.add_argument("--out", type=Path, default=Path("sdrf-model-bench-v1.tar.gz"))
    return p


# ---------------------------------------------------------------- select / freeze

def _write_manifest(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def cmd_select(args) -> int:
    import requests

    from sdrf_model_bench.freeze import SkipDataset, freeze_dataset
    from sdrf_model_bench.select import QTYPES, iter_candidates, made_with_ai, pick_balanced
    from sdrf_model_bench.skills_arm import build_sanitized_plugin, mentioned_accessions, scratch_workspace

    if not args.datasets:
        sys.exit("--datasets is required (path to sdrf-annotated-datasets/datasets)")
    repo = args.datasets.resolve().parent
    probe = scratch_workspace()
    cited = mentioned_accessions(build_sanitized_plugin(args.plugin_src, probe / "plugin", forbidden=[]))
    shutil.rmtree(probe, ignore_errors=True)
    print(f"excluding {len(cited)} accessions cited by the skills")

    rng = random.Random(args.seed)
    by_type: dict[str, list[dict]] = {q: [] for q in QTYPES}
    for cand in iter_candidates(args.datasets):
        if cand["accession"] not in cited and not EXCLUDED_TEMPLATES & set(cand["templates"]):
            by_type[cand["qtype"]].append(cand)
    session = requests.Session()
    pool, log = [], []
    for qtype in QTYPES:
        cands = by_type[qtype]
        rng.shuffle(cands)
        frozen = 0
        for cand in cands:
            if frozen >= args.pool_per_type:
                break
            acc = cand["accession"]
            if made_with_ai(repo, Path(cand["truth_path"]).resolve().relative_to(repo)):
                log.append((acc, "AI provenance"))
                continue
            try:
                meta = freeze_dataset(acc, Path(cand["truth_path"]), args.data, session,
                                      extra_meta={k: cand[k] for k in ("qtype", "templates", "organism", "n_rows")})
            except SkipDataset as exc:
                log.append((acc, str(exc)))
                continue
            except Exception as exc:  # network hiccup or odd record: skip, keep going
                log.append((acc, f"error: {exc!r}"[:120]))
                continue
            pool.append({**cand, **meta, "quality": meta["pride_quality"]})
            frozen += 1
            print(f"  froze {acc} ({qtype}, quality {meta['pride_quality']:.2f})")
        print(f"{qtype}: pool {frozen} of {len(cands)} candidates")

    picked = pick_balanced(pool, args.seed, per_type=args.per_type)
    keep = {p["accession"] for p in picked}
    for p in pool:
        if p["accession"] not in keep:
            shutil.rmtree(args.data / "evidence" / p["accession"], ignore_errors=True)
            (args.data / "truth" / f"{p['accession']}.reference.tsv").unlink(missing_ok=True)
    for p in picked:
        meta_path = args.data / "evidence" / p["accession"] / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["tier"] = p["tier"]
        meta_path.write_text(json.dumps(meta, indent=1, sort_keys=True))
    _write_manifest(args.data / "manifest.tsv", picked)
    (args.data / "selection_log.tsv").write_text("".join(f"{a}\t{why}\n" for a, why in log))
    print(f"selected {len(picked)} datasets -> {args.data / 'manifest.tsv'}")
    return 0


def cmd_replace(args) -> int:
    """Replace datasets one for one, keeping every other selection (and its finished runs) intact."""
    import requests

    from sdrf_model_bench.freeze import SkipDataset, freeze_dataset
    from sdrf_model_bench.runner import load_manifest
    from sdrf_model_bench.select import eligible_replacement, iter_candidates, made_with_ai
    from sdrf_model_bench.skills_arm import build_sanitized_plugin, mentioned_accessions, scratch_workspace

    if not args.datasets or not args.accessions:
        sys.exit("--datasets and --accessions are required")
    repo = args.datasets.resolve().parent
    manifest = load_manifest(args.data / "manifest.tsv")
    probe = scratch_workspace()
    cited = mentioned_accessions(build_sanitized_plugin(args.plugin_src, probe / "plugin", forbidden=[]))
    shutil.rmtree(probe, ignore_errors=True)
    candidates = [c for c in iter_candidates(args.datasets)
                  if c["accession"] not in cited and not EXCLUDED_TEMPLATES & set(c["templates"])]
    log = (args.data / "selection_log.tsv").read_text() if (args.data / "selection_log.tsv").exists() else ""
    session = requests.Session()
    for drop in args.accessions.split(","):
        old = next(m for m in manifest if m["accession"] == drop)
        pool = sorted((c for c in candidates if c["qtype"] == old["qtype"]), key=lambda c: c["accession"])
        random.Random(f"{args.seed}:{drop}").shuffle(pool)
        new = None
        for cand in pool:
            acc = cand["accession"]
            if acc in {m["accession"] for m in manifest}:
                continue
            if made_with_ai(repo, Path(cand["truth_path"]).resolve().relative_to(repo)):
                continue
            try:
                meta = freeze_dataset(acc, Path(cand["truth_path"]), args.data, session,
                                      extra_meta={k: cand[k] for k in ("qtype", "templates", "organism", "n_rows")})
            except Exception:  # SkipDataset or a network/record problem: try the next one
                continue
            if eligible_replacement(cand, meta["pride_quality"], old["tier"], manifest):
                new = {**cand, **meta, "tier": old["tier"]}
                break
            shutil.rmtree(args.data / "evidence" / acc, ignore_errors=True)
            (args.data / "truth" / f"{acc}.reference.tsv").unlink(missing_ok=True)
        if new is None:
            print(f"{drop}: no eligible {old['qtype']}/{old['tier']} replacement found; kept")
            continue
        meta_path = args.data / "evidence" / new["accession"] / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["tier"] = old["tier"]
        meta_path.write_text(json.dumps(meta, indent=1, sort_keys=True))
        shutil.rmtree(args.data / "evidence" / drop, ignore_errors=True)
        (args.data / "truth" / f"{drop}.reference.tsv").unlink(missing_ok=True)
        manifest = [new if m["accession"] == drop else m for m in manifest]
        log += f"{drop}\t{args.reason}; replaced by {new['accession']}\n"
        print(f"{drop} -> {new['accession']} ({old['qtype']}/{old['tier']}, quality {new['pride_quality']:.2f})")
    _write_manifest(args.data / "manifest.tsv", manifest)
    (args.data / "selection_log.tsv").write_text(log)
    return 0


def cmd_freeze(args) -> int:
    from sdrf_model_bench.freeze import freeze_dataset
    from sdrf_model_bench.runner import load_manifest

    if not args.datasets:
        sys.exit("--datasets is required")
    for row in load_manifest(args.data / "manifest.tsv"):
        acc = row["accession"]
        old = json.loads((args.data / "evidence" / acc / "meta.json").read_text())
        keep = {k: old[k] for k in ("qtype", "templates", "organism", "n_rows", "tier") if k in old}
        freeze_dataset(acc, args.datasets / acc / f"{acc}.sdrf.tsv", args.data, extra_meta=keep)
        print("refroze", acc)
    return 0


# ---------------------------------------------------------------- run / score / report

def cmd_run(args) -> int:
    from sdrf_model_bench.config import load_models, load_pricing
    from sdrf_model_bench.providers import find_claude
    from sdrf_model_bench.runner import RunConfig, load_manifest, plan_runs, run_matrix
    from sdrf_model_bench.skills_arm import build_sanitized_plugin, scratch_workspace

    specs = load_models(args.models)
    if args.only:
        wanted = set(args.only.split(","))
        specs = [s for s in specs if s.id in wanted]
        missing = wanted - {s.id for s in specs}
        if missing:
            sys.exit(f"unknown or disabled model ids: {sorted(missing)}")
    manifest = load_manifest(args.data / "manifest.tsv")
    if args.accessions:
        subset = set(args.accessions.split(","))
        manifest = [m for m in manifest if m["accession"] in subset]
    replicates = {k: int(v) for k, v in (x.split(":") for x in args.replicates.split(",") if x)}
    keys = plan_runs(specs, manifest, replicates)
    if args.manuscript != "both":
        keys = [k for k in keys if k.manuscript == (args.manuscript == "on")]

    plugin_dir = None
    if any(s.arm == "skills" for s in specs):
        plugin_dir = build_sanitized_plugin(args.plugin_src, scratch_workspace() / "sdrf-skills",
                                            forbidden=[m["accession"] for m in load_manifest(args.data / "manifest.tsv")])
    cfg = RunConfig(data_dir=args.data, outputs=args.outputs, pricing=load_pricing(args.pricing),
                    plugin_dir=plugin_dir, claude_bin=find_claude(args.claude_bin), max_workers=args.workers)
    print(f"{len(keys)} runs across {len(specs)} model-arms")
    try:
        results = run_matrix(specs, keys, cfg)
    finally:
        if plugin_dir:
            shutil.rmtree(plugin_dir.parent, ignore_errors=True)
    errors = sum("error" in r.get("flags", []) for r in results)
    print(f"done: {len(results)} runs, {errors} crashed (re-run the same command to retry them)")
    return 0


def cmd_score(args) -> int:
    from sdrf_model_bench.config import ModelSpec
    from sdrf_model_bench.judge import judge
    from sdrf_model_bench.providers import make_generate
    from sdrf_model_bench.scoring_run import score_tree
    from sdrf_model_bench.validator import validate

    judge_fn = None
    if not args.no_judge:
        gen = make_generate(ModelSpec(id="judge", provider=args.judge_provider, model=args.judge_model, arm="raw"))
        judge_fn = lambda truth, pred: judge(gen, truth, pred)  # noqa: E731
    records = score_tree(args.outputs, args.data, validate, judge_fn, rescore=args.rescore,
                         deterministic_only=args.deterministic_only)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r) + "\n" for r in records))
    print(f"scored {len(records)} runs -> {args.out}")
    return 0


def cmd_report(args) -> int:
    from sdrf_model_bench.config import load_models
    from sdrf_model_bench.report import render_backups, render_slide, summarise

    records = [json.loads(line) for path in args.results for line in path.read_text().splitlines() if line.strip()]
    if args.manuscript != "both":
        records = [r for r in records if bool(r["manuscript"]) == (args.manuscript == "on")]
    if args.deterministic:  # one rubric for every record, when only some of them were judged
        records = [{**r, "headline": r["deterministic"], "judge": None} for r in records]
    summary = summarise(records)
    seen = {r["model_id"] for r in records}
    # only collaborator slots (custom providers) are shown as awaiting results; other disabled
    # entries were dropped on purpose (e.g. a probe that did not work)
    pending = [s.id.removesuffix("-raw") for s in load_models(args.models, include_disabled=True)
               if s.id not in seen and not s.enabled and s.provider == "custom"]
    args.out.mkdir(parents=True, exist_ok=True)
    from sdrf_model_bench.score import baseline_for_data
    baseline = baseline_for_data(args.data)
    if not args.collaborators_only:  # a pooled slide averages configurations over different dataset sets
        render_slide(summary, args.out / "slide", pending=pending, baseline=baseline)
        render_slide(summary, args.out / "slide-dark", theme="dark", pending=pending, baseline=baseline)
        render_backups(records, summary, args.out)
    from sdrf_model_bench.report import render_collaborators
    render_collaborators(records, args.out)
    render_collaborators(records, args.out, theme="dark")
    print(f"wrote slide + backups to {args.out}")
    for r in summary:
        cost = f"${r['cost_usd']:.3f}" if r["cost_usd"] is not None else f"{r['minutes'] or 0:.1f} min"
        print(f"  {r['model_id']:22s} {r['headline']:5.1f} ±{r['headline_sem']:4.1f}  {cost:>9s}  "
              f"{r['tokens'] / 1000:6.0f}k tok  flags={r['flags']}")
    return 0


def cmd_prompt(args) -> int:
    from sdrf_model_bench.evidence import load_evidence
    from sdrf_model_bench.prompts import build_messages
    from sdrf_model_bench.runner import load_manifest, output_budget

    accs = [args.accession] if args.accession else [r["accession"] for r in load_manifest(args.data / "manifest.tsv")]
    out = {}
    for acc in accs:
        messages, info = build_messages(load_evidence(args.data, acc), args.manuscript == "on")
        out[f"{acc}__ms-{args.manuscript}"] = {"messages": messages, "max_output_tokens": output_budget(args.data, acc),
                                                **info}
    print(json.dumps(out, indent=1))
    return 0


# ---------------------------------------------------------------- pack

def pack(root: Path, out: Path) -> Path:
    root = Path(root).resolve()

    def keep(info: tarfile.TarInfo):
        parts = Path(info.name).parts[1:]
        if any(p in PACK_EXCLUDE or p.endswith((".egg-info", ".tar.gz")) for p in parts):
            return None
        return info

    with tarfile.open(out, "w:gz") as tar:
        tar.add(root, arcname="sdrf-model-bench", filter=keep)
    return Path(out)


def cmd_pack(args) -> int:
    out = pack(args.root, args.out)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"select": cmd_select, "replace": cmd_replace, "freeze": cmd_freeze, "run": cmd_run, "score": cmd_score,
            "report": cmd_report, "prompt": cmd_prompt, "pack": cmd_pack}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
