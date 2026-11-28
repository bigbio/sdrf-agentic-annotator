#!/usr/bin/env python3
"""Can an SDRF of this deposit ever be checked for run coverage? Decided from the PRIDE file list alone.

usage: sdrf_deliverable.py EVIDENCE/files.json      prints {"deliverable": bool, "reason": str}

The coverage audit before a contribution needs every run to be listed: runs inside a .rar, .7z or .tar archive,
or a zip whose directory could not be read (archive_runs.py records the error), cannot be listed, and a deposit
with no run files has nothing to cover. Such datasets are dropped before annotation with --skip_undeliverable,
since an SDRF of them would be held back after the review. The rules are those of the coverage audit: runs end
in .raw, .wiff, .wiff2, .mzml, .mzxml, .d or .mgf, or are Bruker .d.zip folders; any other archive in the list
(.raw.zip and .wiff.zip included) is unlisted. A list that cannot be read never drops a dataset. Exits 0 in every case.
"""
import json
import sys

RUN = (".raw", ".wiff", ".wiff2", ".mzml", ".mzxml", ".d", ".mgf")
RUN_ARCHIVE = (".d.zip", ".raw.zip", ".wiff.zip")
ARCH = (".zip", ".tar", ".tar.gz", ".tgz", ".7z", ".rar", ".gz")


def _names(fj):
    return [str(f.get("fileName") if isinstance(f, dict) else f).lower() for f in (fj.get("files") or [])]


def deposit_problem(fj):
    """None when the deposit's runs can be listed, else the reason they cannot."""
    arch = fj.get("archives") or {}
    bad = [n for n, a in arch.items() if isinstance(a, dict) and a.get("error")] if isinstance(arch, dict) else []
    names = _names(fj)
    unlisted = [n for n in names if n.endswith(ARCH) and not n.endswith(".d.zip")]  # as the coverage audit
    if bad or unlisted:
        return f"archive not listed: {(bad or unlisted)[:2]}"
    if not any(n.endswith(RUN) or n.endswith(RUN_ARCHIVE) for n in names):
        return "no run files in the deposit list"
    return None


def main(argv):
    try:
        with open(argv[0]) as fh:
            fj = json.load(fh)
        if isinstance(fj, list):
            fj = {"files": fj}
        why = deposit_problem(fj)
        out = {"deliverable": why is None, "reason": why or ""}
    except Exception as e:  # an unreadable list never drops a dataset
        out = {"deliverable": True, "reason": f"could not read the file list: {type(e).__name__}"}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
