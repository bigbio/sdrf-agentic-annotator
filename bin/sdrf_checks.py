#!/usr/bin/env python3
"""Run the reviewer's deterministic checks once, before the review agent starts.

usage: sdrf_checks.py SDRF OUT.md [--record pride.json]

The `sdrf-adversarial-review` skill asks the reviewer to hash the artifact and to run
`parse_sdrf validate-sdrf` for the active templates, `sdrf-tools check`, `score` and `structure`.
Each of those is a turn of the review model; run here they cost none. OUT.md holds the SHA-256
and every command with its exit code and output. The script never fails: a command that cannot
run is reported in OUT.md.
"""
import csv
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

import sdrf_identity

TIMEOUT = 600


def active_templates(sdrf):
    """Template names in the `comment[sdrf template]` columns (NT=<name>;VV=<version>), in order."""
    with open(sdrf, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        return []
    cols = [i for i, h in enumerate(rows[0]) if h.strip().lower() == "comment[sdrf template]"]
    names = []
    for row in rows[1:]:
        for i in cols:
            if i < len(row):
                for part in row[i].split(";"):
                    part = part.strip()
                    if part.upper().startswith("NT=") and part[3:] and part[3:] not in names:
                        names.append(part[3:])
    return names


def commands(sdrf, record=None):
    """(name, argv) of every check, in the order the skill lists them. Paths are absolute: the commands run in a scratch folder."""
    s = str(Path(sdrf).resolve())
    validate = ["parse_sdrf", "validate-sdrf", "-s", s]
    for t in active_templates(sdrf):
        validate += ["-t", t]
    validate.append("--use_ols_cache_only")
    cmds = [
        ("parse_sdrf validate-sdrf " + " ".join(validate[4:]), validate),
        ("sdrf-tools structure", ["sdrf-tools", "structure", s]),
        ("sdrf-tools check", ["sdrf-tools", "check", s]),
        ("sdrf-tools score", ["sdrf-tools", "score", s]),
        ("parse_sdrf convert-openms -t2", ["parse_sdrf", "convert-openms", "-s", s, "-t2"]),
    ]
    if record:
        cmds.append(("sdrf-tools reconcile", ["sdrf-tools", "reconcile", s, "--record", str(Path(record).resolve())]))
    return cmds


def run_command(cmd):
    """Exit code and combined output; convert-openms writes files, so every command runs in a scratch folder."""
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT)
    return p.returncode, (p.stdout + p.stderr).strip()


def report(sdrf, record=None, run=run_command, limit=6000):
    sdrf = Path(sdrf)
    out = [
        f"# Deterministic checks of {sdrf.name}",
        "",
        "Run by the pipeline on this exact file before the review. Use these results; do not run these commands again.",
        "",
        f"SHA-256: {hashlib.sha256(sdrf.read_bytes()).hexdigest()}",
        f"Active templates (from comment[sdrf template]): {', '.join(active_templates(sdrf)) or 'none declared'}",
        "",
    ]
    for name, cmd in commands(sdrf, record):
        try:
            code, text = run(cmd)
        except Exception as e:  # noqa: BLE001 - a check that cannot run is a result, not a crash
            code, text = "not run", f"{type(e).__name__}: {e}"
        if len(text) > limit:
            text = text[:limit] + f"\n[cut: {len(text) - limit} more characters]"
        out += [f"## {name} (exit {code})", "", "```", text, "```", ""]
    out.append(sdrf_identity.section(sdrf))
    return "\n".join(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 0
    sdrf, out = argv[0], argv[1]
    record = argv[argv.index("--record") + 1] if "--record" in argv else None
    if record and not Path(record).is_file():
        record = None
    try:
        text = report(sdrf, record)
    except Exception as e:  # noqa: BLE001
        text = f"# Deterministic checks\n\nThe checks could not run ({type(e).__name__}: {e}). Run them yourself.\n"
    Path(out).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
