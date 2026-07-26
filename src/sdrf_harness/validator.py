from __future__ import annotations
import subprocess
from collections import Counter
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
