#!/usr/bin/env python3
"""Read the fragmentation method from the instrument method embedded in the deposited Thermo RAW files.

usage: raw_dissociation.py PXD OUT.json [--max-files 2] [--bytes 8388608]

A Thermo RAW file starts with its instrument method as UTF-16 text. The script asks the PRIDE API for the
RAW files of the project, reads only the first `--bytes` of one or two of them with an HTTP range request,
and looks for the activation type in three layouts:

  A  `Activation Type: HCD` / `ActivationType = CID` lines (LTQ Velos, Orbitrap Elite, Fusion, Lumos, ...)
  B  `<Fragmentation_HCD ...>25</Fragmentation_HCD>` with a collision energy above zero (Q Exactive family)
  C  a legacy ion-trap method with an `Activation Q` (the resonance-CID parameter, which HCD does not have) but no
     activation type: CID, with medium confidence

OUT.json has `value` (the types found, the SDRF values, a confidence) or `value: null` and a `reason`. Several types
in one method (for example CID and ETD) are reported together with `ambiguous: true`, since the header does not say
which scan events are enabled. A lookup that fails writes an `error` and still exits 0, so a run goes on without it.
"""
import argparse
import collections
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request

TERMS = {
    "CID": ("collision-induced dissociation", "MS:1000133"),
    "HCD": ("beam-type collision-induced dissociation", "MS:1000422"),
    "ETD": ("electron transfer dissociation", "MS:1000598"),
    "PQD": ("pulsed q dissociation", "MS:1000599"),
    "EThcD": ("electron-transfer/higher-energy collision dissociation", "MS:1002631"),
    "ECD": ("electron capture dissociation", "MS:1000250"),
}
ACTIVATION = re.compile(r"^(?:MS\d+ )?Activation ?Type ?[:=] ?(CID|HCD|ETD|PQD|ECD|EThcD|ETciD)\b", re.IGNORECASE)
XML_TAG = re.compile(r"<Fragmentation_(HCD|CID)\b[^>]*>\s*([0-9.]+)\s*</Fragmentation_\1>")
LEGACY = re.compile(r"^(?:MS\d+ )?Activation Q ?[:=] ?[0-9.]+")
CANON = {"CID": "CID", "HCD": "HCD", "ETD": "ETD", "PQD": "PQD", "ECD": "ECD", "ETHCD": "EThcD", "ETCID": "EThcD"}


def lines_of(head):
    """The text lines of a RAW header, decoding UTF-16 at both byte alignments."""
    out = []
    for offset in (0, 1):
        for line in re.split(r"[\r\n\x00]+", head[offset:].decode("utf-16le", errors="ignore")):
            line = re.sub(r"\s+", " ", line.strip())
            if 3 < len(line) < 200 and line.isprintable():
                out.append(line)
    return out


def parse_method(head):
    """What the header of one RAW file says about the activation: types with counts and the lines they come from."""
    if head[:2] != b"\x01\xa1" or "Finnigan" not in head[2:40].decode("utf-16le", errors="ignore"):
        return {"thermo_raw": False, "types": {}, "rule": None, "evidence": []}
    types, evidence, rule = collections.Counter(), [], None
    lines = lines_of(head)
    for line in lines:
        m = ACTIVATION.match(line)
        if m:
            types[CANON[m.group(1).upper()]] += 1
            rule = "A"
            if line not in evidence and len(evidence) < 6:
                evidence.append(line)
    if not types:
        for line in lines:
            for m in XML_TAG.finditer(line):
                if float(m.group(2)) > 0:
                    types[m.group(1).upper()] += 1
                    rule = "B"
                    if line not in evidence and len(evidence) < 6:
                        evidence.append(line)
    legacy = [line for line in dict.fromkeys(lines) if LEGACY.match(line)]
    if not types and legacy:
        types["CID"] = 1
        rule = "C"
        evidence = legacy[:4]
    return {"thermo_raw": True, "types": dict(types), "rule": rule, "evidence": evidence}


def decide(parsed):
    """One answer for the dataset from the parsed RAW files."""
    usable = [p for p in parsed if p["thermo_raw"]]
    if not usable:
        return None, "no Thermo RAW file could be read"
    found = sorted({t for p in usable for t in p["types"]})
    if not found:
        return None, "the method text names no activation type"
    rules = {p["rule"] for p in usable if p["types"]}
    same = len({tuple(sorted(p["types"])) for p in usable if p["types"]}) == 1
    ambiguous = len(found) > 1 or not same
    confidence = "low" if ambiguous else ("medium" if rules == {"C"} else "high")
    return {
        "types": found,
        "sdrf": [f"NT={TERMS[t][0]};AC={TERMS[t][1]}" for t in found],
        "confidence": confidence,
        "ambiguous": ambiguous,
        "rule": "".join(sorted(r for r in rules if r)),
    }, None


RETRY_CODES = (403, 429, 500, 502, 503, 504)


def open_url(request, timeout):
    """urlopen with a back-off on the codes that a busy server answers when several readers ask at once."""
    for attempt in range(5):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES or attempt == 4:
                raise
        except urllib.error.URLError:
            if attempt == 4:
                raise
        time.sleep(5 * 3**attempt + random.uniform(0, 5))


def raw_files(pxd):
    """RAW files of the project as (name, size, https url), smallest first."""
    files, page = [], 0
    while True:
        with open_url(f"https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{pxd}/files?pageSize=100&page={page}", 60) as r:
            chunk = json.load(r)
        files += chunk
        page += 1
        if len(chunk) < 100 or page > 8:
            break
    out = []
    for f in files:
        if f["fileCategory"]["value"] == "RAW" and f["fileName"].lower().endswith(".raw"):
            link = next((loc["value"] for loc in f["publicFileLocations"] if loc["name"].startswith("FTP")), None)
            if link:
                out.append((f["fileName"], f.get("fileSizeBytes", 0), link.replace("ftp://", "https://")))
    return sorted(out, key=lambda x: x[1])


def read_head(url, nbytes):
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{nbytes - 1}"})
    with open_url(request, 90) as r:
        return r.read(nbytes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pxd")
    ap.add_argument("out")
    ap.add_argument("--max-files", type=int, default=2)
    ap.add_argument("--bytes", type=int, default=8388608)
    args = ap.parse_args()
    result = {"accession": args.pxd, "generated_by": "bin/raw_dissociation.py", "files": [], "value": None}
    try:
        candidates = raw_files(args.pxd)
        if not candidates:
            result["reason"] = "the deposit lists no .raw file"
        picked = candidates[: args.max_files] if len(candidates) <= args.max_files else [candidates[0], candidates[len(candidates) // 2]][: args.max_files]
        for name, size, url in picked:
            parsed = parse_method(read_head(url, args.bytes))
            result["files"].append({"file": name, "size": size, **parsed})
        if result["files"]:
            result["value"], reason = decide(result["files"])
            if reason:
                result["reason"] = reason
    except Exception as e:  # a failed lookup must not stop the run
        result["error"] = f"{type(e).__name__}: {e}"
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    v = result["value"]
    print(f"{args.pxd}: {','.join(v['types']) + ' (' + v['confidence'] + ')' if v else 'no value: ' + result.get('reason', result.get('error', '?'))}")


if __name__ == "__main__":
    sys.exit(main())
