from __future__ import annotations
import glob
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from .models import Verdict

def _col(header, name):
    return header.index(name) if name in header else None

def structural_check(sdrf_path):
    lines = Path(sdrf_path).read_text().splitlines()
    if not lines:
        return 0, 0
    h = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:] if ln.strip()]
    ragged = sum(1 for r in rows if len(r) != len(h))
    sn = 0
    bi, ti, fr = (_col(h, "characteristics[biological replicate]"),
                  _col(h, "comment[technical replicate]"),
                  _col(h, "comment[fraction identifier]"))
    collisions = 0
    if None not in (bi, ti, fr):
        key = Counter((r[sn], r[bi], r[ti], r[fr]) for r in rows if len(r) > max(bi, ti, fr))
        collisions = sum(1 for v in key.values() if v > 1)
    return ragged, collisions

def validate(sdrf_path, templates=("ms-proteomics",), run_cli=True) -> Verdict:
    ragged, collisions = structural_check(sdrf_path)
    errors = []
    if ragged:
        errors.append(f"{ragged} ragged rows")
    if collisions:
        errors.append(f"{collisions} coordinate collisions")
    if run_cli:
        cmd = ["parse_sdrf", "validate-sdrf", "--sdrf_file", str(sdrf_path)]
        for t in templates:
            cmd += ["-t", t]
        cmd += ["--use_ols_cache_only"]
        out = subprocess.run(cmd, capture_output=True, text=True)
        tail = (out.stdout + out.stderr).strip().splitlines()
        last = tail[-1] if tail else ""
        if "Well done" not in last and "only warnings" not in last:
            errors.append("parse_sdrf: " + last[:200])
    return Verdict(passed=not errors, errors=errors, collisions=collisions, ragged=ragged)

def normalise_term(s: str) -> str:
    return re.sub(r"[\s\-_]+", " ", s.strip().lower()).strip()

_PAIR = re.compile(r"NT=([^;\t]+);AC=([A-Za-z]+[:_]\d+)")

def accession_check(sdrf_path, labels: dict) -> list:
    out = []
    seen = set()
    for line in Path(sdrf_path).read_text().splitlines()[1:]:
        for m in _PAIR.finditer(line):
            nt, ac = m.group(1), m.group(2).replace("_", ":").upper()
            if (nt, ac) in seen:
                continue
            seen.add((nt, ac))
            real = labels.get(ac)
            if real is None:
                continue
            a, b = normalise_term(nt), normalise_term(real)
            if a != b and a not in b and b not in a:
                out.append((nt, ac, real))
    return out

@dataclass
class Report:
    passed: bool
    collisions: int = 0
    ragged: int = 0
    accession_mismatches: list = field(default_factory=list)
    cli_errors: list = field(default_factory=list)

def load_ontology_labels(cache_dir=None) -> dict:
    import pandas as pd
    cache_dir = cache_dir or os.path.expanduser("~/Library/Caches/sdrf-pipelines/ontologies/")
    labels = {}
    for f in glob.glob(os.path.join(cache_dir, "*.parquet")):
        try:
            df = pd.read_parquet(f, columns=["accession", "label"])
        except Exception:
            continue
        for a, l in zip(df["accession"], df["label"]):
            if isinstance(a, str):
                labels.setdefault(a.strip().upper().replace("_", ":"), str(l).strip())
    return labels

def full_report(sdrf_path, labels=None, run_cli=False) -> Report:
    ragged, collisions = structural_check(sdrf_path)
    mism = accession_check(sdrf_path, labels) if labels else []
    cli_errors = []
    if run_cli:
        v = validate(sdrf_path, run_cli=True)
        cli_errors = [e for e in v.errors if e.startswith("parse_sdrf")]
    passed = collisions == 0 and ragged == 0 and not mism and not cli_errors
    return Report(passed=passed, collisions=collisions, ragged=ragged,
                  accession_mismatches=mism, cli_errors=cli_errors)
