#!/usr/bin/env python3
"""Sample identity of an SDRF: one source name is one biological sample.

usage: sdrf_identity.py SDRF      prints a markdown section for the reviewer's checks

A source name that carries two or more distinct `characteristics[biological replicate]` values names
several independent samples with one identifier, so quantification keyed on the source collapses them.
Independent biological replicates need distinct source names; technical repeats and fractions of one
sample keep the same source name and differ in `comment[technical replicate]` or the fraction column.
Rows with an empty source name (unused multiplex channels) are ignored. A file without a source or
replicate column is not checked. The script never fails.
"""
import csv
import sys
from pathlib import Path

LIMIT = 10


def _key(value):
    try:
        return (0, float(value), value)
    except ValueError:
        return (1, 0.0, value)


def problems(sdrf):
    """[(source name, [distinct biological replicate values])] for sources with more than one value."""
    with open(sdrf, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    if "source name" not in head or "characteristics[biological replicate]" not in head:
        return []
    si, bi = head.index("source name"), head.index("characteristics[biological replicate]")
    seen = {}
    for row in rows[1:]:
        if len(row) <= max(si, bi) or not row[si].strip():
            continue
        seen.setdefault(row[si], set()).add(row[bi].strip())
    return [(s, sorted(v, key=_key)) for s, v in seen.items() if len(v) > 1]


def section(sdrf):
    found = problems(sdrf)
    out = ["## Sample identity (sdrf_identity.py)", ""]
    if not found:
        out.append("No source name carries more than one biological replicate value.")
        return "\n".join(out) + "\n"
    out += [
        f"BLOCKER: {len(found)} source names carry more than one biological replicate value. One source name is one "
        "biological sample: independent biological replicates need a distinct source name each, while technical "
        "repeats and fractions of one sample keep the same source name and differ in technical replicate or "
        "fraction. If the repeats are really technical, correct the replicate values instead. Check the study "
        "design before choosing.",
        "",
    ]
    out += [f"- {s}: biological replicate {', '.join(v)}" for s, v in found[:LIMIT]]
    if len(found) > LIMIT:
        out.append(f"- ... and {len(found) - LIMIT} more")
    return "\n".join(out) + "\n"


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 0
    try:
        print(section(Path(argv[0])), end="")
    except Exception as e:  # noqa: BLE001 - a check that cannot run is a result, not a crash
        print(f"## Sample identity\n\nThe check could not run ({type(e).__name__}: {e}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
