"""Lay the collaborators' SDRFs out as an outputs tree, so `sdrf-bench score` scores them with
the same rubric, validator and references as our own runs.

  external/dai/    Chengxin Dai: sdrf-skills workflow with network access (PRIDE, FTP, Europe PMC,
                   OLS), plus the minutes a human curator needed for the same dataset
                   (benchmark_data.py, from his manual-vs-skills benchmark)
  external/jonas/  Jonas Scheid, bigbio/sdrf-skills PR #24: one Claude Science session with the
                   skills and one without, on PXD037221 (E. coli TMT) and PXD058436 (MHCquant2)

    uv run python import_external.py && uv run sdrf-bench score --data data-ext \
        --outputs outputs-external --out results/collaborators/external.jsonl --no-judge
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs-external"

# PR #24's reports: PXD058436's two arms ran in separate sessions ($14.06 with, $11.41 without);
# PXD037221's arms shared one session, so their cost cannot be split.
# sdrf-annotated-datasets' PXD058436 reference was contributed by Jonas (2026-07-10), so scoring his
# own SDRFs against it is circular; flagged, and left out of the headline slide.
SAME_AUTHOR = {"PXD058436"}
JONAS_COST = {("PXD058436", "skills"): 14.06, ("PXD058436", "raw"): 11.41}


def write_run(config: str, acc: str, sdrf: Path, usage: dict) -> None:
    run = OUT / config / f"{acc}__ms-off__r1"
    run.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sdrf, run / "sdrf.tsv")
    (run / "usage.json").write_text(json.dumps({"provider": "external", "flags": [], "usage": {}, **usage}, indent=1))
    (run / "score.json").unlink(missing_ok=True)


def main() -> None:
    spec = importlib.util.spec_from_file_location("dai", HERE / "external" / "dai" / "benchmark_data.py")
    dai = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dai)
    for acc, human_min, skills_min, _fresh_in, _out in dai.DATASETS:
        write_run("dai-skills", acc, HERE / "external" / "dai" / f"{acc}.sdrf.tsv",
                  {"model_id": "dai-skills", "arm": "external", "model": "Dai (skills, own session)",
                   "wall_s": skills_min * 60, "human_min": human_min, "cost_usd": None})
    for acc in ("PXD037221", "PXD058436"):
        for arm, suffix, label in (("skills", "with_skills", "Jonas (skills, own session)"),
                                   ("raw", "without_skills", "Jonas (no skills, own session)")):
            write_run(f"jonas-{arm}", acc, HERE / "external" / "jonas" / f"{acc}_{suffix}.sdrf.tsv",
                      {"model_id": f"jonas-{arm}", "arm": "external", "model": label,
                       "wall_s": None, "cost_usd": JONAS_COST.get((acc, arm)),
                       "flags": ["reference_same_author"] if acc in SAME_AUTHOR else []})
    print(f"wrote {sum(1 for _ in OUT.glob('*/*/sdrf.tsv'))} runs under {OUT}")


if __name__ == "__main__":
    main()
