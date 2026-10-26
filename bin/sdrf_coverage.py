#!/usr/bin/env python3
"""Deterministic coverage and file-existence precheck of one SDRF against its PRIDE deposit.

Reads every `comment[data file]` value of the SDRF, fetches the PRIDE deposit file list and
writes a coverage report (JSON) that the reviewer must fold into its verdict:

- matched / missing: SDRF data files whose basename is / is not in the deposit
  (a missing file is a file-mapping hallucination)
- deposit_data_count: deposit files of the class an SDRF lists, RAW files, or peak lists
  (mzML, MGF, ...) when the deposit has no RAW files. Search and result files are not counted.
- coverage: fraction of those deposit files that the SDRF represents

If PRIDE cannot be reached after a few attempts the report has status `not_verifiable`, so the
gate never silently passes on an unverifiable deposit.
"""

import argparse
import json
import os
import sys
import time
import urllib.request

PRIDE_PROJECTS = "https://www.ebi.ac.uk/pride/ws/archive/v3/projects"
PAGE_SIZE = 100
RETRY_DELAYS = (10, 30)

RAW_CATEGORIES = {"RAW"}
PEAK_CATEGORIES = {"PEAK", "MZML", "MZXML", "MGF"}
RAW_EXTENSIONS = (".raw", ".raw.zip", ".wiff", ".wiff2", ".wiff.scan", ".d", ".d.zip", ".d.tar", ".d.tar.gz")
PEAK_EXTENSIONS = (".mzml", ".mzml.gz", ".mzxml", ".mgf", ".mgf.gz", ".mzdata", ".ms2")


def fetch_json(url, sleep=time.sleep):
    """GET a JSON document, retrying transient failures with a growing delay."""
    for delay in RETRY_DELAYS + (None,):
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except Exception:
            if delay is None:
                raise
            sleep(delay)


def parse_files(data):
    """Map file name -> PRIDE file category ('' if unknown) for one /files response."""
    files = {}
    if not isinstance(data, list):
        raise ValueError(f"unexpected PRIDE file list shape: {type(data).__name__}")
    for entry in data:
        if isinstance(entry, str):
            name = entry.split("/")[-1]
            if name:
                files[name] = ""
            continue
        name = None
        for location in entry.get("publicFileLocations", []):
            value = location.get("value", "")
            if value.lower().startswith(("ftp://", "https://", "http://", "prd_ascp@")):
                name = os.path.basename(value.split("/")[-1])
                break
        name = name or entry.get("fileName") or entry.get("accession")
        if name:
            files[name] = (entry.get("fileCategory") or {}).get("value", "")
    return files


def fetch_deposit(pxd, fetch=fetch_json):
    """File name -> category for the whole deposit: /files/all, else the paginated /files."""
    errors = []
    try:
        files = parse_files(fetch(f"{PRIDE_PROJECTS}/{pxd}/files/all"))
        if files:
            return files
        errors.append("/files/all returned no files")
    except Exception as e:
        errors.append(f"/files/all: {e}")
    try:
        files = {}
        page = 0  # PRIDE pages are 0-based
        while True:
            data = fetch(f"{PRIDE_PROJECTS}/{pxd}/files?page={page}&pageSize={PAGE_SIZE}")
            files.update(parse_files(data))
            if len(data) < PAGE_SIZE:
                break
            page += 1
        if files:
            return files
        errors.append("paginated /files returned no files")
    except Exception as e:
        errors.append(f"/files: {e}")
    raise RuntimeError(" / ".join(errors))


def is_raw(name, category):
    return category in RAW_CATEGORIES or (not category and name.lower().endswith(RAW_EXTENSIONS))


def is_peak(name, category):
    return category in PEAK_CATEGORIES or (not category and name.lower().endswith(PEAK_EXTENSIONS))


def sdrf_data_files(sdrf_path):
    """Basenames of every `comment[data file]` value; a cell may hold several, comma-separated."""
    files = set()
    with open(sdrf_path) as fh:
        header = [h.strip().lower() for h in fh.readline().rstrip("\n").split("\t")]
        columns = [i for i, h in enumerate(header) if h == "comment[data file]"]
        for line in fh:
            cells = line.rstrip("\n").split("\t")
            for i in columns:
                if i < len(cells):
                    for part in cells[i].split(","):
                        if part.strip():
                            files.add(os.path.basename(part.strip()))
    return files


def coverage_report(pxd, sdrf_files, deposit):
    matched = sorted(f for f in sdrf_files if f in deposit)
    missing = sorted(f for f in sdrf_files if f not in deposit)

    # Denominator: the deposit files an SDRF lists, RAW files, or peak lists without RAW files
    raw = sorted(n for n, c in deposit.items() if is_raw(n, c))
    peak = sorted(n for n, c in deposit.items() if is_peak(n, c))
    denominator, data = ("RAW", raw) if raw else (("PEAK", peak) if peak else (None, []))
    represented = [f for f in data if f in sdrf_files]
    coverage = len(represented) / len(data) if data else None

    return {
        "pxd": pxd,
        "status": "ok",
        "sdrf_files": len(sdrf_files),
        "matched": matched,
        "matched_count": len(matched),
        "missing": missing,
        "missing_count": len(missing),
        "deposit_files_count": len(deposit),
        "denominator": denominator,
        "deposit_data_count": len(data),
        "represented_data_count": len(represented),
        "coverage": round(coverage, 6) if coverage is not None else None,
    }


def not_verifiable_report(pxd, sdrf_files, error):
    return {
        "pxd": pxd,
        "status": "not_verifiable",
        "error": error,
        "sdrf_files": len(sdrf_files),
        "matched": [],
        "matched_count": None,
        "missing": [],
        "missing_count": None,
        "deposit_files_count": None,
        "denominator": None,
        "deposit_data_count": None,
        "represented_data_count": None,
        "coverage": None,
    }


def main(argv=None, fetch=fetch_json):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pxd", required=True)
    parser.add_argument("--sdrf", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    sdrf_files = sdrf_data_files(args.sdrf)
    try:
        report = coverage_report(args.pxd, sdrf_files, fetch_deposit(args.pxd, fetch))
    except Exception as e:
        report = not_verifiable_report(args.pxd, sdrf_files, str(e))
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
