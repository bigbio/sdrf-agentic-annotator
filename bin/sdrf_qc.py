#!/usr/bin/env python3
"""What the raw files of a dataset show (prideQC), as Markdown for the evidence sheet and the checks.

usage: sdrf_qc.py sheet QC_DIR            summary for the annotate agent's evidence sheet
       sdrf_qc.py compare QC_DIR SDRF     SDRF values the raw files contradict, for the reviewer

QC_DIR holds one or more prideQC `annotations.tsv` files (any depth), whose rows are
`data_file, field, value, evidence (observed|inferred|unavailable), method, support, total, detail`.
Observed values (instrument model, dissociation, collision energy) are read from the raw file; inferred ones
(acquisition method, suggested tolerances) come from a heuristic. Exploratory evidence (TMT reporter ions,
mass shifts) is not read. Nothing here ever fails: with no or unreadable files the output is empty.
"""
import collections
import csv
import json
import re
import statistics
import sys
from pathlib import Path, PurePosixPath

csv.field_size_limit(sys.maxsize)  # mass-shift cells exceed the 128 KB default

HCD = {"MS:1000422", "MS:1002481"}  # beam-type CID and higher-energy beam-type CID are both HCD
# Dissociation names an SDRF writes without an accession, and the accessions they mean
DISSOCIATION_NAMES = [  # checked in this order: HCD and EThcD names also contain "collision-induced"
    ("ethcd", {"MS:1002631"}), ("hcd", HCD), ("higher energy", HCD), ("beam-type", HCD),
    ("electron transfer", {"MS:1000598"}), ("etd", {"MS:1000598"}),
    ("cid", {"MS:1000133"}), ("collision-induced", {"MS:1000133"}),
]
VENDOR = {"thermo", "fisher", "scientific", "orbitrap", "instrument", "model", "bruker", "sciex", "waters"}
RULES = (
    "Read from the raw files by prideQC. An *observed* value (instrument model, dissociation, collision energy) "
    "outranks the PRIDE record and the paper: if they disagree, say so and use the observed value. An *inferred* "
    "value (acquisition method, suggested tolerances) is a hint to confirm against the paper. The suggested "
    "tolerances come from the measured mass error: that is instrument precision, not the search tolerance the "
    "authors used, so never write it as the SDRF tolerance; use it only to question an implausible one."
)


def _json(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _record(rows):
    """One data file's fields from its annotations rows ({field: (value, evidence)})."""
    rec = {}
    get = lambda f: rows.get(f, (None, "unavailable"))
    details, ev = get("instrument_details")
    details = _json(details)
    if isinstance(details, dict) and (details.get("model") or details.get("name")):
        rec["instrument_model"] = details.get("model") or details.get("name")
    diss = _json(get("dissociation_ms2")[0])
    if isinstance(diss, list) and diss:
        rec["dissociation"] = [(d.get("accession"), d.get("name"), d.get("count")) for d in diss if isinstance(d, dict)]
    ce = _json(get("collision_energy_ms2")[0])
    if isinstance(ce, list) and ce:
        rec["collision_energy"] = [str(x) for x in ce]
    acq = _json(get("acquisition_method")[0])
    if isinstance(acq, str) and acq:
        cv = _json(get("acquisition_method_evidence")[0]) or {}
        rec["acquisition_method"] = (acq, ((cv.get("cv_term") or {}).get("accession")))
    for field, key in (("suggested_precursor_search_tolerance_ppm", "precursor_tolerance_ppm"),
                       ("suggested_fragment_search_tolerance_ppm", "fragment_tolerance_ppm"),
                       ("suggested_fragment_search_tolerance_da", "fragment_tolerance_da")):
        v = _json(get(field)[0])
        if isinstance(v, dict) and isinstance(v.get("suggested_tolerance"), (int, float)):
            rec[key] = round(float(v["suggested_tolerance"]), 4)
    return rec


def read_qc(qc_dir):
    """{data_file: record} from every annotations.tsv under qc_dir; {} when there are none."""
    files = {}
    root = Path(qc_dir)
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("annotations.tsv")):
        try:
            by_file = collections.defaultdict(dict)
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                for r in csv.DictReader(fh, delimiter="\t"):
                    if r.get("data_file") and r.get("field"):
                        by_file[r["data_file"]][r["field"]] = (r.get("value"), r.get("evidence"))
            for name, rows in by_file.items():
                rec = _record(rows)
                if rec:
                    files[name] = rec
        except (OSError, csv.Error):
            continue
    return files


def summarise(files):
    """Per field: the commonest value, its support, the total, the evidence kind and the other values."""
    out = {}
    def add(key, values, evidence):
        values = [v for v in values if v not in (None, "")]
        if not values:
            return
        c = collections.Counter(values)
        top, n = c.most_common(1)[0]
        out[key] = {"value": top, "support": n, "total": len(files), "evidence": evidence,
                    "others": {k: v for k, v in c.items() if k != top}}
    recs = list(files.values())
    add("instrument_model", [r.get("instrument_model") for r in recs], "observed")
    add("dissociation", [", ".join(f"{name} ({acc})" for acc, name, _ in r["dissociation"]) if r.get("dissociation") else None for r in recs], "observed")
    add("collision_energy", [", ".join(r["collision_energy"]) if r.get("collision_energy") else None for r in recs], "observed")
    add("acquisition_method", [r["acquisition_method"][0] if r.get("acquisition_method") else None for r in recs], "inferred")
    for key, unit in (("precursor_tolerance_ppm", "ppm"), ("fragment_tolerance_ppm", "ppm"), ("fragment_tolerance_da", "Da")):
        vals = [r[key] for r in recs if key in r]
        if vals:
            out[key] = {"value": f"{statistics.median(vals):.3g} {unit} (median; {min(vals):.3g}-{max(vals):.3g})",
                        "support": len(vals), "total": len(files), "evidence": "inferred", "others": {}}
    return out


def _key(name):
    n = PurePosixPath(str(name).strip()).name.lower()
    for ext in (".gz", ".zip", ".raw", ".mzml", ".mzxml", ".wiff", ".d"):
        if n.endswith(ext):
            n = n[: -len(ext)]
    return n


def _nt(cell):
    m = re.search(r"NT=([^;]+)", cell or "")
    return (m.group(1) if m else cell or "").strip()


def _ac(cell):
    m = re.search(r"AC=([^;]+)", cell or "")
    return m.group(1).strip().upper() if m else None


def same_instrument(sdrf_cell, model):
    norm = lambda s: "".join(w for w in re.findall(r"[a-z0-9]+", s.lower().replace("-", " ")) if w not in VENDOR)
    return norm(_nt(sdrf_cell)) == norm(model)


def _acq_kind(text, accession=None):
    t = f"{text or ''} {accession or ''}".lower()
    if "independent" in t or "pride:0000450" in t or re.search(r"\bdia\b", t):
        return "DIA"
    if "dependent" in t or "pride:0000627" in t or re.search(r"\bdda\b", t):
        return "DDA"
    return None


def compare(sdrf_path, files):
    """SDRF cells the raw files contradict, per data file: {"mismatches", "matched_files", "sdrf_files"}."""
    with open(sdrf_path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    h = [c.strip().lower() for c in rows[0]]
    col = lambda name: h.index(name) if name in h else None
    i_file = col("comment[data file]")
    qc = {_key(k): (k, v) for k, v in files.items()}
    mismatches, seen, matched, sdrf_files = [], set(), set(), set()
    if i_file is None:
        return {"mismatches": [], "matched_files": 0, "sdrf_files": 0}
    for r in rows[1:]:
        if i_file >= len(r) or not r[i_file].strip():
            continue
        k = _key(r[i_file])
        sdrf_files.add(k)
        if k not in qc:
            continue
        matched.add(k)
        name, rec = qc[k]
        cell = lambda c: r[col(c)] if col(c) is not None and col(c) < len(r) else ""
        checks = []
        if rec.get("instrument_model") and cell("comment[instrument]") and not same_instrument(cell("comment[instrument]"), rec["instrument_model"]):
            checks.append(("comment[instrument]", cell("comment[instrument]"), rec["instrument_model"], "observed"))
        diss = cell("comment[dissociation method]")
        if rec.get("dissociation") and diss and diss.lower() not in ("not available", "not applicable"):
            qacc = {a for a, _, _ in rec["dissociation"] if a}
            sacc = _ac(diss)
            if sacc:
                ok = sacc in qacc or (sacc in HCD and bool(qacc & HCD))
            else:
                name = _nt(diss).lower()
                meant = next((acc for word, acc in DISSOCIATION_NAMES if word in name), None)
                ok = bool(meant & qacc) or (bool(meant & HCD) and bool(qacc & HCD)) if meant else \
                    any(name in (n or "").lower() for _, n, _ in rec["dissociation"])
            if not ok:
                checks.append(("comment[dissociation method]", diss, ", ".join(f"{n} ({a})" for a, n, _ in rec["dissociation"]), "observed"))
        acq = cell("comment[proteomics data acquisition method]")
        if rec.get("acquisition_method") and acq and _acq_kind(acq) and _acq_kind(*rec["acquisition_method"]) and _acq_kind(acq) != _acq_kind(*rec["acquisition_method"]):
            checks.append(("comment[proteomics data acquisition method]", acq, rec["acquisition_method"][0], "inferred"))
        for column, sdrf_value, qc_value, evidence in checks:
            if (column, name) not in seen:
                seen.add((column, name))
                mismatches.append({"column": column, "file": name, "sdrf": sdrf_value, "qc": qc_value, "evidence": evidence})
    return {"mismatches": mismatches, "matched_files": len(matched), "sdrf_files": len(sdrf_files)}


def sheet_markdown(files):
    if not files:
        return ""
    s = summarise(files)
    lines = ["## Raw-file QC (prideQC)", "", RULES, "", f"{len(files)} raw files with QC.", "",
             "| field | value | runs | evidence | other values (runs) |", "|---|---|---|---|---|"]
    for key, v in s.items():
        others = "; ".join(f"{k} ({n})" for k, n in v["others"].items()) or "-"
        lines.append(f"| {key.replace('_', ' ')} | {v['value']} | {v['support']}/{v['total']} | {v['evidence']} | {others} |")
    return "\n".join(lines) + "\n"


def checks_markdown(sdrf_path, files):
    if not files:
        return ""
    try:
        found = compare(sdrf_path, files)
    except (OSError, IndexError, csv.Error):
        return ""
    lines = ["## Raw-file QC comparison (prideQC)", "", RULES, "",
             f"{found['matched_files']} of {found['sdrf_files']} SDRF data files have QC."]
    groups = collections.defaultdict(list)
    for m in found["mismatches"]:
        groups[(m["column"], m["sdrf"], m["qc"], m["evidence"])].append(m["file"])
    if not groups:
        lines += ["", "No SDRF value checked here is contradicted by the raw files."]
    else:
        lines += ["", "| column | SDRF value | raw files show | evidence | files |", "|---|---|---|---|---|"]
        for (column, sdrf_value, qc_value, evidence), names in groups.items():
            shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
            lines.append(f"| {column} | {sdrf_value} | {qc_value} | {evidence} | {len(names)}: {shown} |")
    return "\n".join(lines).rstrip() + "\n"


def main(argv):
    try:
        if argv[:1] == ["sheet"] and len(argv) >= 2:
            sys.stdout.write(sheet_markdown(read_qc(argv[1])))
        elif argv[:1] == ["compare"] and len(argv) >= 3:
            sys.stdout.write(checks_markdown(argv[2], read_qc(argv[1])))
        else:
            sys.stderr.write(__doc__)
    except Exception as e:  # never fail the task
        sys.stderr.write(f"sdrf_qc.py: {type(e).__name__}: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
