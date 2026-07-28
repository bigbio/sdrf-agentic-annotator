from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Bundle

RAW_EXTS = frozenset({"raw", "wiff", "d", "raw.gz", "wiff.gz"})
PEAKLIST_EXTS = frozenset({"mgf", "mzml", "mzxml", "ms2", "pkl"})


def _ext(name: str) -> str:
    n = name.lower()
    for e in ("raw.gz", "wiff.gz"):
        if n.endswith("." + e):
            return e
    return n.rsplit(".", 1)[-1] if "." in n else ""


def _taxid(accession) -> str:
    m = re.search(r"(\d+)", str(accession or ""))
    return m.group(1) if m else ""


def _find_deposited_sdrf(files_json):
    """Return (filename, https_url) of a deposited SDRF.

    Matches names like sdrf.tsv / SDRF.tsv / <PXD>.sdrf.tsv / sdrf-<topic>.tsv.
    The URL is the file's FTP publicFileLocation with ftp:// rewritten to the
    https mirror; None if not present.
    """
    for f in files_json:
        name = f.get("fileName", "")
        low = name.lower()
        if "sdrf" in low and low.endswith(".tsv"):
            url = None
            for loc in f.get("publicFileLocations", []) or []:
                v = loc.get("value", "")
                if "ftp.pride" in v and v.startswith(("ftp://", "https://")):
                    url = v.replace("ftp://", "https://", 1)
                    break
            return name, url
    return None, None


def parse_pride_project(project_json: dict, files_json: list) -> Bundle:
    orgs = [
        (o.get("name"), _taxid(o.get("accession", "")))
        for o in (project_json.get("organisms") or [])
    ]
    instr = [
        i.get("name")
        for i in (project_json.get("instruments") or [])
        if i.get("name")
    ]
    files = [
        {"name": f.get("fileName", ""), "ext": _ext(f.get("fileName", ""))}
        for f in files_json
    ]
    deposited, deposited_url = _find_deposited_sdrf(files_json)
    return Bundle(
        accession=project_json.get("accession", ""),
        repository="pride",
        organisms=orgs,
        instruments=instr,
        files=files,
        deposited_sdrf=deposited,
        deposited_sdrf_url=deposited_url,
    )


def is_annotatable(bundle: Bundle) -> tuple[bool, str]:
    exts = {f["ext"] for f in bundle.files}
    if exts & RAW_EXTS:
        return True, ""
    if exts & PEAKLIST_EXTS:
        return False, "peak-list-only deposit"
    return False, "no vendor-native raw files"


def fetch_bundle(accession, repository, cache_dir, session=None):
    """Network fetch (PRIDE v3). Caches raw JSON; delegates parsing to parse_pride_project."""
    import requests

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    s = session or requests.Session()
    base = f"https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{accession}"
    proj = s.get(base, timeout=60).json()
    files = s.get(base + "/files/all?pageSize=3000", timeout=120).json()
    files = files if isinstance(files, list) else files.get("_embedded", {}).get("files", [])
    (cache_dir / f"{accession}.project.json").write_text(json.dumps(proj))
    b = parse_pride_project(proj, files)
    (cache_dir / f"{accession}.bundle.json").write_text(b.to_json())
    return b


def deposited_sdrf_url(accession, ym, filename) -> str:
    return f"https://ftp.pride.ebi.ac.uk/pride/data/archive/{ym}/{accession}/{filename}"


def fetch_deposited_sdrf(bundle, ym=None, session=None):
    url = getattr(bundle, "deposited_sdrf_url", None)
    if not url:
        if not (ym and bundle.deposited_sdrf):
            return None
        url = deposited_sdrf_url(bundle.accession, ym, bundle.deposited_sdrf)
    if session is None:
        import requests
        session = requests.Session()
    resp = session.get(url, timeout=120)
    if getattr(resp, "status_code", 200) != 200:
        return None
    return resp.text
