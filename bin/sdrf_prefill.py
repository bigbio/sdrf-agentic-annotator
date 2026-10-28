#!/usr/bin/env python3
"""Prefill what the PRIDE record already states, so the annotate agent starts from verified facts.

usage: sdrf_prefill.py EVIDENCE_DIR OUTPUT.json

Reads evidence/pride.json and evidence/files.json (written by `sdrf-tools fetch`) and writes
<PXD>.prefill.json. Every value comes from a structured field of the record or from the digest
sentences of its protocols (the enzyme dictionary of sdrf-tools), never from a model. Each entry
names its source. A value the record does not state is left out; a value found only by a pattern
in the free text has `"basis": "text"` and the agent has to confirm it.
"""
import json
import re
import sys
from pathlib import Path

from tools.record_reconcile import proteases_in_record, prose

# Accessions of the enzymes that sdrf-skills writes in its own examples; the others get a name only.
ENZYME_ACCESSION = {"Trypsin": "MS:1001251", "Lys-C": "MS:1001309", "Chymotrypsin": "MS:1001306"}

LABELS = (
    (r"\bTMT\s*-?\s*(\d+)\s*-?\s*plex\b|\bTMT\s*-?\s*(\d+)\b", "TMT"),
    (r"\bTMT\b", "TMT"),
    (r"\biTRAQ\s*-?\s*(\d+)?(?:\s*-?\s*plex)?", "iTRAQ"),
    (r"\bSILAC\b", "SILAC"),
    (r"\bdimethyl(?:ation|\s+label\w*)", "dimethyl"),
)
ACQUISITION = (
    (r"\bDIA\b|data[- ]independent|\bSWATH\b|\bdiaPASEF\b", "DIA"),
    (r"\bDDA\b|data[- ]dependent", "DDA"),
)
# Deposited search outputs that `sdrf-tools search-params` can read
SEARCH_PARAMS = re.compile(r"(^|/)(mqpar\.xml|parameters\.txt|fragger\.params|summary\.txt)$|\.(msf|pdresult)$|diann.*\.log$|report\.log\.txt$", re.IGNORECASE)
RESULT_FILES = re.compile(r"\.(mzid|mztab)(\.gz)?$|\.pride\.mztab\.gz$|\.xml(\.gz)?$", re.IGNORECASE)


def cv(term):
    return {"name": term.get("name"), "accession": term.get("accession")}


def fact(value, source, basis="record", **extra):
    return {"value": value, "source": source, "basis": basis, **extra}


def organisms(record):
    """NEWT ids are NCBI taxonomy ids; 'Homo sapiens (human)' becomes 'Homo sapiens'."""
    out = []
    for o in record.get("organisms") or []:
        taxon = re.sub(r"\s*\(.*\)\s*$", "", o.get("name") or "")
        acc = o.get("accession") or ""
        out.append(fact(taxon, "pride.json:organisms", accession=("NCBITaxon:" + acc.split(":")[1]) if acc.startswith("NEWT:") else acc))
    return out


def text_hits(patterns, text):
    found = []
    for pat, label in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m and label not in [f["value"] for f in found]:
            found.append(fact(label, "text", "text", match=m.group(0)))
    return found


def files(evidence):
    listing = json.loads((evidence / "files.json").read_text())
    runs, other = listing.get("files") or [], listing.get("other_files") or []
    return {
        "run_files": runs,
        "run_count": len(runs),
        "search_parameter_files": [f for f in other if SEARCH_PARAMS.search(f)],
        "result_files": [f for f in other if RESULT_FILES.search(f)],
        "other_files": other,
        "urls": {k: v for k, v in (listing.get("urls") or {}).items() if SEARCH_PARAMS.search(k)},
    }


def prefill(evidence):
    evidence = Path(evidence)
    record = json.loads((evidence / "pride.json").read_text())
    protocols = prose(record, "sampleProcessingProtocol", "dataProcessingProtocol", "projectDescription", "title")
    enzymes = [fact(name, "protocol digest sentences", "text", accession=ENZYME_ACCESSION.get(name)) for name in proteases_in_record(record)]
    labels = text_hits(LABELS, protocols) + [fact(q.get("name"), "pride.json:quantificationMethods", accession=q.get("accession")) for q in record.get("quantificationMethods") or []]
    return {
        "accession": record.get("accession"),
        "generated_by": "bin/sdrf_prefill.py",
        "note": "Values from the PRIDE record (basis 'record') are stated by the submitter's deposit. Values with basis 'text' were found by a pattern in the free text: confirm them. A field that is missing here was not stated; do not assume it.",
        "organism": organisms(record),
        "instrument": [fact(i.get("name"), "pride.json:instruments", accession=i.get("accession")) for i in record.get("instruments") or []],
        "organism_part": [fact(p.get("name"), "pride.json:organismParts", accession=p.get("accession")) for p in record.get("organismParts") or []],
        "disease": [fact(d.get("name"), "pride.json:diseases", accession=d.get("accession")) for d in record.get("diseases") or []],
        "experiment_type": [fact(e.get("name"), "pride.json:experimentTypes", accession=e.get("accession")) for e in record.get("experimentTypes") or []],
        "cleavage_agent": enzymes,
        "label": labels or [fact("label free sample", "no labelling keyword in the record", "absence")],
        "acquisition": text_hits(ACQUISITION, protocols),
        "modifications_reported": [fact(m.get("name"), "pride.json:identifiedPTMStrings", accession=m.get("accession")) for m in record.get("identifiedPTMStrings") or []],
        "files": files(evidence),
    }


if __name__ == "__main__":
    out = prefill(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {sys.argv[2]}: {len(out['organism'])} organism, {len(out['instrument'])} instrument, {len(out['cleavage_agent'])} enzyme, {out['files']['run_count']} run files")
