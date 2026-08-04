"""Evidence-gather + coverage manifest — the deterministic, headless Phase-1b step.

For each accession it assembles the ``evidence`` dict coverage scores against:

  * cached Bundle + PRIDE project JSON        (``fetch_bundle`` output)
  * columns already present in a deposited SDRF (sharpens the fill rules)
  * techsdrf empirical results, if available   (instrument/label/mods/tolerances)

then scores it against the auto-selected template combination and emits a
ranked, tier-split manifest (qwen / claude). All external inputs are injectable
providers with cache-file defaults, so the core is testable without network and
the real providers (techsdrf CPU array, deposited-SDRF fetch) wire in at the edge:

  * deposited SDRF text  -> ``{acc}.deposited.sdrf.tsv`` in the cache dir
  * techsdrf results     -> ``{acc}.techsdrf.json``      in the cache dir
"""

from __future__ import annotations

import json
from pathlib import Path

from .coverage import gather_signals, route, template_coverage


def parse_deposited_columns(text: str) -> set[str]:
    """Column names from a deposited SDRF header (first line, tab-separated).

    SDRF files intentionally repeat column headers for multi-valued columns; we
    only need the *set* of names, so duplicates collapse naturally. Never use
    pandas here — it mangles repeated headers with ``.N`` suffixes.
    """
    if not text:
        return set()
    header = text.splitlines()[0] if text.splitlines() else ""
    return {c.strip() for c in header.split("\t") if c.strip()}


def _default_deposited_text(cache_dir: Path, accession: str):
    p = cache_dir / f"{accession}.deposited.sdrf.tsv"
    return p.read_text() if p.exists() else None


def _default_techsdrf(cache_dir: Path, accession: str):
    p = cache_dir / f"{accession}.techsdrf.json"
    return json.loads(p.read_text()) if p.exists() else None


def build_evidence(
    accession: str,
    cache_dir,
    get_deposited_text=None,
    get_techsdrf=None,
) -> dict | None:
    """Assemble the evidence dict for one cached accession, or None if its
    bundle cache is absent. ``get_deposited_text`` / ``get_techsdrf`` are
    ``(cache_dir, accession) -> value | None`` providers (cache-file defaults)."""
    from .models import Bundle

    cache_dir = Path(cache_dir)
    bpath = cache_dir / f"{accession}.bundle.json"
    if not bpath.exists():
        return None
    bundle = Bundle.from_json(bpath.read_text())
    ppath = cache_dir / f"{accession}.project.json"
    project = json.loads(ppath.read_text()) if ppath.exists() else {}

    dep = (get_deposited_text or _default_deposited_text)(cache_dir, accession)
    tech = (get_techsdrf or _default_techsdrf)(cache_dir, accession)
    deposited_columns = parse_deposited_columns(dep) if dep else set()
    evidence = gather_signals(
        bundle, project, techsdrf=tech, deposited_columns=deposited_columns
    )
    # techsdrf verifying acquisition means the acquisition method column is solid
    if tech and tech.get("acquisition"):
        evidence["acquisition_confident"] = True
    return evidence


def score_dataset(
    accession: str, cache_dir, templates=None, threshold=0.7, **providers
) -> dict | None:
    """Evidence + coverage report for one accession (None if uncached)."""
    evidence = build_evidence(accession, cache_dir, **providers)
    if evidence is None:
        return None
    report = template_coverage(evidence, templates)
    report["accession"] = accession
    report["tier"] = route(report, threshold)
    return report


def build_manifest(accessions, cache_dir, threshold=0.7, **providers) -> dict:
    """Score a list of accessions into a ranked, tier-split manifest.

    Datasets are ranked by score (desc). Uncached accessions are reported under
    ``skipped`` rather than silently dropped.
    """
    datasets, skipped = [], []
    for acc in accessions:
        rep = score_dataset(acc, cache_dir, threshold=threshold, **providers)
        (skipped if rep is None else datasets).append(acc if rep is None else rep)
    datasets.sort(key=lambda r: r["score"], reverse=True)
    by_tier = {"qwen": [], "claude": []}
    for r in datasets:
        by_tier[r["tier"]].append(r["accession"])
    return {
        "threshold": threshold,
        "counts": {
            "scored": len(datasets),
            "qwen": len(by_tier["qwen"]),
            "claude": len(by_tier["claude"]),
            "skipped": len(skipped),
        },
        "by_tier": by_tier,
        "skipped": skipped,
        "datasets": datasets,
    }


def _parse_args(argv):
    import argparse

    p = argparse.ArgumentParser(prog="sdrf_agentic_annotator.evidence")
    p.add_argument("--accessions-file", required=True)
    p.add_argument("--cache", required=True, help="cache dir with *.bundle.json")
    p.add_argument("--out", required=True, help="manifest JSON output path")
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
    manifest = build_manifest(accs, ns.cache, threshold=ns.threshold)
    Path(ns.out).write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
