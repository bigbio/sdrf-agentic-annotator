"""One-time evidence capture from PRIDE and Europe PMC. Runs never touch the network."""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from sdrf_model_bench.evidence import evidence_dir

PRIDE = "https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{acc}"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
METHODS_RE = re.compile(r"method|experimental|materials|procedure|sample prep", re.I)
SAMPLE_RE = re.compile(r"sample|patient|donor|cohort|cell|tissue|condition|replicate|tmt|channel|treat", re.I)
QUALITY_LISTS = ("organisms", "organismParts", "diseases", "instruments", "identifiedPTMStrings",
                 "quantificationMethods")


class SkipDataset(Exception):
    pass


def pride_quality(pride: dict) -> float:
    checks = [bool(pride.get(k)) for k in QUALITY_LISTS]
    checks += [len(pride.get(k) or "") >= 200 for k in ("sampleProcessingProtocol", "dataProcessingProtocol")]
    return sum(checks) / len(checks)


def raw_file_names(files: list[dict]) -> list[str]:
    return sorted(f["fileName"] for f in files if (f.get("fileCategory") or {}).get("value") == "RAW")


def has_deposited_sdrf(files: list[dict]) -> bool:
    return any("sdrf" in f.get("fileName", "").lower() for f in files)


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def extract_methods(xml: str) -> str:
    root = ET.fromstring(xml)
    body = root.find(".//body")
    if body is None:
        return ""
    parts = []
    for sec in body.iter("sec"):
        title = sec.find("title")
        if title is not None and METHODS_RE.search(_text(title)):
            parts.append(_text(sec))
    if not parts:
        parts.append(_text(body))
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
        if not license_.startswith("cc"):
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
    raws = raw_file_names(files)
    if not raws:
        raise SkipDataset("no RAW files listed")
    ms = find_manuscript(session, pride)
    if not ms:
        raise SkipDataset("no CC-licensed open-access full text")
    methods = extract_methods(ms["xml"])
    if len(methods) < 500:
        raise SkipDataset("methods text too short")
    d = evidence_dir(data_dir, acc)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pride.json").write_text(json.dumps(pride, indent=1, sort_keys=True))
    (d / "files.json").write_text(json.dumps(raws, indent=1))
    (d / "manuscript.txt").write_text(methods)
    meta = {"accession": acc, "pmid": ms["pmid"], "pmcid": ms["pmcid"], "license": ms["license"],
            "pride_quality": pride_quality(pride), "n_raw_files": len(raws),
            "has_deposited_sdrf": deposited_sdrf, **(extra_meta or {})}
    (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    truth_dir = Path(data_dir) / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(truth_path, truth_dir / f"{acc}.sdrf.tsv")
    return meta
