"""Ground-truth filtering, quantification typing and stratified, seeded selection."""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

from sdrf_model_bench.sdrf_io import column_values, first_value, is_na, read_sdrf

# Rows per truth file. TMT rows are file x channel, so it gets more room (and TMT is scarce).
MAX_ROWS = {"TMT": 100, "LFQ": 60, "DIA": 60}
DIA_RE = re.compile(r"data.independent|\bdia\b|swath", re.I)
AI_RE = re.compile(r"sdrf-skills|annotator|agentic|co-authored-by:\s*claude|generated with claude", re.I)
QTYPES = ("TMT", "LFQ", "DIA")


def quant_type(header, rows) -> str | None:
    label_cells = [v for r in rows for v in column_values(header, r, "comment[label]")]
    labels = " ".join(label_cells).lower()
    if "tmt" in labels:
        # the truth must encode multiplexing (one row per channel), not one generic label per file
        return "TMT" if len({v.strip().lower() for v in label_cells}) >= 2 else None
    if any(x in labels for x in ("silac", "itraq", "dimethyl")):
        return None
    if "label free" in labels or "label-free" in labels:
        acq = " ".join(v for r in rows
                       for v in column_values(header, r, "comment[proteomics data acquisition method]"))
        return "DIA" if DIA_RE.search(acq) else "LFQ"
    return None


def truth_ok(text: str, max_rows: int = MAX_ROWS["LFQ"]) -> bool:
    header, rows = read_sdrf(text)
    return "comment[data file]" in header and 1 <= len(rows) <= max_rows


def made_with_ai(repo: Path, path: Path) -> bool:
    log = subprocess.run(["git", "-C", str(repo), "log", "--format=%B", "--", str(path)],
                         capture_output=True, text=True).stdout
    return bool(AI_RE.search(log))


def describe_truth(text: str) -> dict:
    header, rows = read_sdrf(text)
    organism = (first_value(header, rows[0], "characteristics[organism]") or "").lower() if rows else ""
    cell_lines = [first_value(header, r, "characteristics[cell line]") for r in rows]
    return {
        "qtype": quant_type(header, rows),
        "n_rows": len(rows),
        "organism": organism,
        "non_human": bool(organism) and "homo sapiens" not in organism,
        "cell_line_only": bool(rows) and all(not is_na(c) for c in cell_lines),
        "templates": sorted({t for r in rows for v in column_values(header, r, "comment[sdrf template]")
                             for t in [v.split("NT=")[-1].split(";")[0].strip()] if t}),
    }


def iter_candidates(datasets_dir: Path):
    for path in sorted(Path(datasets_dir).glob("PXD*/PXD*.sdrf.tsv")):
        if path.name != f"{path.parent.name}.sdrf.tsv":
            continue
        text = path.read_text(errors="replace")
        if not truth_ok(text, max(MAX_ROWS.values())):
            continue
        info = describe_truth(text)
        if info["qtype"] and info["n_rows"] <= MAX_ROWS[info["qtype"]]:
            yield {"accession": path.parent.name, "truth_path": str(path), **info}


def pick_balanced(pool: list[dict], seed: int, per_type: int = 4) -> list[dict]:
    """Per quant type, split the pool into quality tertiles and draw half rich, half poor;
    then swap in non-human studies until >=3 and cap cell-line-only studies at 2."""
    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[dict]] = {}
    for qtype in QTYPES:
        items = sorted((p for p in pool if p["qtype"] == qtype), key=lambda p: (p["quality"], p["accession"]))
        third = max(1, len(items) // 3)
        for tier, part in (("poor", items[:third]), ("rich", items[-third:])):
            part = [dict(p, tier=tier) for p in part]
            rng.shuffle(part)
            buckets[(qtype, tier)] = part
    k = per_type // 2
    chosen = {key: items[:k] for key, items in buckets.items()}
    spare = {key: items[k:] for key, items in buckets.items()}

    def count(pred):
        return sum(pred(x) for items in chosen.values() for x in items)

    def swap(want, avoid, stop):
        for key in sorted(chosen):
            for i, x in enumerate(chosen[key]):
                if stop():
                    return
                if avoid(x):
                    alt = next((s for s in spare[key] if want(s)), None)
                    if alt:
                        spare[key].remove(alt)
                        chosen[key][i] = alt

    swap(lambda s: s["non_human"] and not s["cell_line_only"], lambda x: not x["non_human"],
         lambda: count(lambda x: x["non_human"]) >= 3)
    swap(lambda s: not s["cell_line_only"], lambda x: x["cell_line_only"],
         lambda: count(lambda x: x["cell_line_only"]) <= 2)
    return [x for key in sorted(chosen) for x in chosen[key]]
