"""One-time evidence capture from PRIDE and Europe PMC. Runs never touch the network."""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from sdrf_model_bench.evidence import evidence_dir
from sdrf_model_bench.score import file_key
from sdrf_model_bench.sdrf_io import column_values, read_sdrf

PRIDE = "https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{acc}"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
METHODS_RE = re.compile(
    r"^\s*(?:[\dIVX]+\.?\s+)?(?:star\s+|online\s+)?(?:materials?\s*(?:and|&)\s*methods|methods?(?:\s*(?:and|&)\s*materials?)?"
    r"|experimental(?:\s+(?:procedures?|section|design|methods?))?|procedures?)\s*$",
    re.I,
)
STOP_RE = re.compile(r"^\s*(?:[\dIVX]+\.?\s+)?(?:results|discussion|conclusions?|acknowledg|references|supplementary|data availability|author contributions|funding)", re.I)
SAMPLE_RE = re.compile(r"sample|patient|donor|cohort|cell|tissue|condition|replicate|tmt|channel|treat", re.I)
QUALITY_LISTS = ("organisms", "organismParts", "diseases", "instruments", "identifiedPTMStrings",
                 "quantificationMethods")


MIN_METHODS_CHARS = 500


class SkipDataset(Exception):
    pass


def pride_quality(pride: dict) -> float:
    checks = [bool(pride.get(k)) for k in QUALITY_LISTS]
    checks += [len(pride.get(k) or "") >= 200 for k in ("sampleProcessingProtocol", "dataProcessingProtocol")]
    return sum(checks) / len(checks)


def raw_file_names(files: list[dict]) -> list[str]:
    return sorted(f["fileName"] for f in files if (f.get("fileCategory") or {}).get("value") == "RAW")


def scope_to_truth(raws: list[str], truth_text: str) -> list[str]:
    """Only the raw files the curators annotated. PRIDE often holds more (e.g. DDA library runs next
    to the DIA runs); asking for all of them measures scoping, not annotation, and breaks the
    output budget. The names are public in PRIDE, so this reveals scope, not answers."""
    header, rows = read_sdrf(truth_text)
    curated = {file_key(v) for row in rows for v in column_values(header, row, "comment[data file]")}
    return [f for f in raws if file_key(f) in curated]


def has_deposited_sdrf(files: list[dict]) -> bool:
    """A submitter-deposited SDRF. PRIDE also republishes community SDRFs (our ground truth) as
    *_community_annotated.sdrf.tsv; those are not counted here."""
    names = (f.get("fileName", "").lower() for f in files)
    return any("sdrf" in n and "community_annotated" not in n for n in names)


def redistributable(license_: str) -> bool:
    """Creative Commons without NoDerivatives: a methods excerpt may be shared in the pack."""
    lic = (license_ or "").lower()
    return lic.startswith("cc") and "nd" not in lic.replace("cc0", "").split("-")


def _text(el) -> str:
    return re.sub(r"\s+", " ", " ".join(el.itertext())).strip()


def _title_matches(el, pattern) -> bool:
    title = el.find("title") if el.tag == "sec" else None
    return title is not None and bool(pattern.search(_text(title)))


def extract_methods(xml: str) -> str:
    """Methods sections (body or back matter) plus sample-related legends; "" when the full text
    has no methods section (e.g. methods only in a supplementary PDF) - such papers are skipped."""
    root = ET.fromstring(xml)
    parts: list[str] = []

    def walk(el):
        children = list(el)
        i = 0
        while i < len(children):
            child = children[i]
            if _title_matches(child, METHODS_RE):
                chunk = [_text(child)]  # the whole section; nested sub-sections are inside
                if len(chunk[0]) < 500:  # empty heading: the methods follow as sibling sections
                    while i + 1 < len(children) and children[i + 1].tag == "sec" \
                            and not _title_matches(children[i + 1], STOP_RE):
                        i += 1
                        chunk.append(_text(children[i]))
                parts.append(" ".join(chunk))
            else:
                walk(child)
            i += 1

    walk(root)
    if len(" ".join(parts)) < MIN_METHODS_CHARS:  # legends alone do not make a methods section
        return ""
    for cap in root.iter("caption"):
        t = _text(cap)
        if SAMPLE_RE.search(t):
            parts.append("Legend: " + t)
    return "\n\n".join(dict.fromkeys(parts))


def fetch_json(session, url, **params):
    r = session.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_files(session, acc: str) -> list[dict]:
    files, page = [], 0
    while True:
        batch = fetch_json(session, PRIDE.format(acc=acc) + "/files", pageSize=100, page=page)
        files += batch
        if len(batch) < 100:
            return files
        page += 1


def find_manuscript(session, pride: dict) -> dict | None:
    for ref in pride.get("references") or []:
        pmid = ref.get("pubmedID")
        if not pmid:
            continue
        res = fetch_json(session, f"{EPMC}/search", query=f"EXT_ID:{pmid} AND SRC:MED",
                         resultType="core", format="json")["resultList"]["result"]
        if not res or not res[0].get("pmcid"):
            continue
        license_ = (res[0].get("license") or "").lower()
        if not redistributable(license_):
            continue
        r = session.get(f"{EPMC}/{res[0]['pmcid']}/fullTextXML", timeout=60)
        if r.status_code == 200 and r.text.lstrip().startswith("<"):
            return {"pmid": pmid, "pmcid": res[0]["pmcid"], "license": license_, "xml": r.text}
    return None


def freeze_dataset(acc: str, truth_path: Path, data_dir: Path, session=None, extra_meta: dict | None = None) -> dict:
    session = session or requests.Session()
    pride = fetch_json(session, PRIDE.format(acc=acc))
    files = fetch_files(session, acc)
    # A deposited SDRF is not exposed: evidence carries RAW file names only and runs are offline.
    # It is recorded as a covariate (it is public, like every curated SDRF - see contamination flag).
    deposited_sdrf = has_deposited_sdrf(files)
    pride_raws = raw_file_names(files)
    raws = scope_to_truth(pride_raws, Path(truth_path).read_text(errors="replace"))
    if not raws:
        raise SkipDataset("no curated RAW files listed in PRIDE")
    ms = find_manuscript(session, pride)
    if not ms:
        raise SkipDataset("no CC-licensed open-access full text")
    methods = extract_methods(ms["xml"])
    if not methods:
        raise SkipDataset("no methods section in the full text")
    d = evidence_dir(data_dir, acc)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pride.json").write_text(json.dumps(pride, indent=1, sort_keys=True))
    (d / "files.json").write_text(json.dumps(raws, indent=1))
    (d / "manuscript.txt").write_text(methods)
    meta = {"accession": acc, "pmid": ms["pmid"], "pmcid": ms["pmcid"], "license": ms["license"],
            "pride_quality": pride_quality(pride), "n_raw_files": len(raws), "n_raw_files_pride": len(pride_raws),
            "has_deposited_sdrf": deposited_sdrf, **(extra_meta or {})}
    (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    truth_dir = Path(data_dir) / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(truth_path, truth_dir / f"{acc}.sdrf.tsv")
    return meta
