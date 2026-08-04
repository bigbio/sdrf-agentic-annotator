"""Phase-1b batch prep — turn a cache of fetched datasets into a work plan.

Scores every cached accession (template-aware coverage), writes a drafting
prompt per qwen-tier dataset, and emits a manifest the cluster batch runner
iterates over (loading Qwen once, then looping loop->techsdrf->refine per
dataset). Claude-tier datasets are listed separately for human/Claude handling.
"""

from __future__ import annotations

import json
from pathlib import Path

from .coverage import gather_signals, route, template_coverage
from .evidence import build_evidence
from .models import Bundle
from .prompt import build_messages


def prepare(accessions, cache_dir, out_dir, threshold: float = 0.7) -> dict:
    """Score + build prompts for cached accessions. Writes {acc}.prompt.json for
    qwen-tier datasets into out_dir and returns the manifest dict."""
    cache_dir, out_dir = Path(cache_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    qwen, claude, skipped = [], [], []
    rows = []
    for acc in accessions:
        bpath = cache_dir / f"{acc}.bundle.json"
        if not bpath.exists():
            skipped.append(acc)
            continue
        bundle = Bundle.from_json(bpath.read_text())
        ppath = cache_dir / f"{acc}.project.json"
        project = json.loads(ppath.read_text()) if ppath.exists() else {}
        evidence = build_evidence(acc, cache_dir) or gather_signals(bundle, project)
        report = template_coverage(evidence)
        tier = route(report, threshold)
        templates = report["templates"]
        gaps = report["hard_gaps"] + report["soft_gaps"]
        rows.append(
            {
                "accession": acc,
                "score": report["score"],
                "tier": tier,
                "templates": templates,
            }
        )
        if tier == "qwen":
            msgs = build_messages(bundle, project, templates, gaps=gaps)
            (out_dir / f"{acc}.prompt.json").write_text(json.dumps(msgs))
            qwen.append(acc)
        else:
            claude.append(
                {"accession": acc, "gaps": report["hard_gaps"], "templates": templates}
            )
    rows.sort(key=lambda r: r["score"], reverse=True)
    manifest = {
        "threshold": threshold,
        "counts": {"qwen": len(qwen), "claude": len(claude), "skipped": len(skipped)},
        "qwen": qwen,
        "claude": claude,
        "skipped": skipped,
        "datasets": rows,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (out_dir / "qwen.manifest.txt").write_text("\n".join(qwen) + ("\n" if qwen else ""))
    return manifest


def _parse_args(argv):
    import argparse

    p = argparse.ArgumentParser(prog="sdrf_agentic_annotator.batch")
    p.add_argument("--accessions-file", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--out", required=True, help="dir for prompts + manifest")
    p.add_argument("--threshold", type=float, default=0.7)
    return p.parse_args(argv)


def main(argv=None) -> int:
    import sys

    ns = _parse_args(argv if argv is not None else sys.argv[1:])
    accs = [
        line.strip()
        for line in Path(ns.accessions_file).read_text().splitlines()
        if line.strip()
    ]
    manifest = prepare(accs, ns.cache, ns.out, threshold=ns.threshold)
    print(json.dumps(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
