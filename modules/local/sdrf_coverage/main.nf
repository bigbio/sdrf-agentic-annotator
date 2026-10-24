/*
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SDRF_COVERAGE - deterministic coverage + file-existence precheck
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A plain (non-agent) process that runs before the adversarial review. For one PRIDE
dataset it:

  1. Reads every `comment[data file]` value from the SDRF (basenames).
  2. Fetches the PRIDE deposit file list for the PXD via the archive REST API.
  3. Computes:
       - matched    : SDRF data files whose basename exists in the deposit
       - missing    : SDRF data files whose basename is NOT in the deposit
                      (a file-mapping hallucination, e.g. a reference to a .raw that
                      does not exist -> improvement 3)
       - deposit_data: number of data-class files in the deposit
       - coverage    : fraction of the deposit's data files that the SDRF represents
  4. Writes a coverage.json that the reviewer MUST incorporate into its verdict.

This is cheap and deterministic, so the expensive adversarial pass only needs to
re-verify on top of it, and the coverage/subset gate (improvement 1) has a solid
numeric basis instead of an LLM guess.
----------------------------------------------------------------------------------------
 */

process SDRF_COVERAGE {

    tag "${pxd}"

    container 'ghcr.io/jonasscheid/nf-agent-sdrf:dev'

    cpus 1
    memory '2 GB'

    // Network is required to fetch the PRIDE file list.
    errorStrategy 'retry'
    maxRetries 3

    input:
    tuple val(pxd), path(sdrf), path(manifest)

    output:
    tuple val(pxd), path("${pxd}.coverage.json"), path(sdrf), path(manifest)

    script:
    """
    python3 <<'PY'
    import json, os, re, subprocess, sys, urllib.request

    pxd = "$pxd"
    sdrf_path = "$sdrf"
    cover_path = "${pxd}.coverage.json"

    # --- 1. extract comment[data file] basenames from the SDRF ---
    # A cell can hold multiple data files comma-separated (e.g. 'raw.d.zip, db.peptides.csv').
    sdrf_files = set()
    with open(sdrf_path) as fh:
        header = fh.readline().rstrip('\\n').split('\\t')
        # SDRF may repeat the column under the same header; use every matching column
        idx = [i for i, h in enumerate(header) if h.strip() == 'comment[data file]']
        for line in fh:
            cols = line.rstrip('\\n').split('\\t')
            for i in idx:
                if i < len(cols) and cols[i].strip():
                    for part in cols[i].split(','):
                        part = part.strip()
                        if part:
                            sdrf_files.add(os.path.basename(part))

    # --- 2. fetch PRIDE deposit file list ---
    # Preferred: /files/all returns the complete list in one call (the same endpoint the annotate
    # skill uses; it may return a bare string array of file paths, or a list of file objects).
    # Fall back to the paginated /files (<=100/page), and to not_verifiable otherwise so the gate
    # never silently passes on an unverifiable deposit.
    deposit_files = set()
    data_categories = {"RAW", "RESULT", "PEAK", "SEARCH", "MZML", "MZXML", "MGF"}
    depos_categories = {}
    try:
        paginated = f"https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{pxd}/files/all"
        req = urllib.request.Request(paginated, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], str):
            # bare string array of file paths
            for p in data:
                name = p.split("/")[-1]
                if name:
                    deposit_files.add(name)
                    depos_categories[name] = ""
        elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            # list of file objects
            for f in data:
                name = None
                for l in f.get("publicFileLocations", []):
                    v = l.get("value", "")
                    if v.lower().startswith(("ftp://", "https://", "http://", "prd_ascp@")):
                        name = os.path.basename(v.split("/")[-1])
                        break
                if not name:
                    name = f.get("fileName") or f.get("accession")
                if name:
                    deposit_files.add(name)
                    depos_categories[name] = f.get("fileCategory", {}).get("value", "")
        else:
            raise ValueError(f"/files/all returned unexpected shape: {type(data)}")
        if len(deposit_files) == 0:
            raise ValueError("/files/all returned no files")
    except Exception as e1:
        # fall back to paginated /files (<=100/page)
        try:
            url = f"https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{pxd}/files"
            pg = 1
            while True:
                paginated = f"{url}?page={pg}"
                req = urllib.request.Request(paginated, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.load(r)
                if not isinstance(data, list) or len(data) == 0:
                    break
                for f in data:
                    name = None
                    loc = f.get("publicFileLocations", [])
                    for l in loc:
                        v = l.get("value", "")
                        if v.lower().startswith(("ftp://", "https://", "http://", "prd_ascp@")):
                            name = os.path.basename(v.split("/")[-1])
                            break
                    cat = f.get("fileCategory", {}).get("value", "")
                    if not name:
                        name = f.get("fileName") or f.get("accession")
                    if name:
                        deposit_files.add(name)
                        depos_categories[name] = cat
                if len(data) < 100:
                    break
                pg += 1
            if len(deposit_files) == 0:
                raise ValueError("paginated /files returned no files")
        except Exception as e2:
            # The gate must not silently pass; surface a not_verifiable status so the
            # reviewer can treat coverage as an important finding.
            report = {
                "pxd": pxd,
                "status": "not_verifiable",
                "error": f"{e1} / {e2}",
                "sdrf_files": sorted(sdrf_files),
                "missing": [],
                "matched": [],
                "deposit_data_count": None,
                "coverage": None,
            }
            with open(cover_path, "w") as fh:
                json.dump(report, fh, indent=2)
            sys.exit(0)

    # --- 3. matching (basename lookup) ---
    matched = sorted(f for f in sdrf_files if f in deposit_files)
    missing = sorted(f for f in sdrf_files if f not in deposit_files)

    # Coverage denominator: deposit files that are actually data (not README/checksum/aux).
    deposit_data = sorted(n for n, c in depos_categories.items()
                          if c in data_categories or n.lower().endswith((".raw", ".wiff", ".wiff.scan", ".mzml", ".mzml.gz", ".mzxml", ".mgf", ".dia", ".d", ".mzdata", ".pep.xml", ".ms2")))
    # Coverage numerator: distinct deposit data files represented by the SDRF.
    represented = [f for f in deposit_data if f in sdrf_files]

    coverage = (len(represented) / len(deposit_data)) if deposit_data else None

    report = {
        "pxd": pxd,
        "status": "ok",
        "sdrf_files": len(sdrf_files),
        "matched": matched,
        "matched_count": len(matched),
        "missing": missing,
        "missing_count": len(missing),
        "deposit_files_count": len(deposit_files),
        "deposit_data_count": len(deposit_data),
        "represented_data_count": len(represented),
        "coverage": round(coverage, 6) if coverage is not None else None,
    }
    with open(cover_path, "w") as fh:
        json.dump(report, fh, indent=2)
    PY
    """
}
