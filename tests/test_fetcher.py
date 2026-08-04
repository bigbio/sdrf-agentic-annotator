import json
from pathlib import Path
from sdrf_agentic_annotator.fetcher import parse_pride_project, is_annotatable

FIX = Path(__file__).parent / "fixtures"

def test_parse_pride_project_extracts_core_fields():
    proj = json.load(open(FIX / "pride_PXDTEST.json"))
    b = parse_pride_project(proj, proj["_files"])
    assert b.accession == "PXDTEST"
    assert ("Homo sapiens", "9606") in b.organisms
    assert "Q Exactive" in b.instruments
    assert any(f["ext"] == "raw" for f in b.files)

def test_is_annotatable_rejects_peaklist_only():
    from sdrf_agentic_annotator.models import Bundle
    b = Bundle(accession="X", repository="pride",
               files=[{"name": "a.mgf", "ext": "mgf"}, {"name": "b.mzML", "ext": "mzml"}])
    ok, reason = is_annotatable(b)
    assert not ok and "peak-list" in reason

def test_is_annotatable_accepts_raw():
    from sdrf_agentic_annotator.models import Bundle
    b = Bundle(accession="X", repository="pride", organisms=[("Homo sapiens", "9606")],
               files=[{"name": "a.raw", "ext": "raw"}])
    ok, _ = is_annotatable(b)
    assert ok


def test_find_deposited_sdrf_bare_name_and_url():
    from sdrf_agentic_annotator.fetcher import parse_pride_project
    files = [
        {"fileName": "run1.raw"},
        {"fileName": "sdrf.tsv", "publicFileLocations": [
            {"name": "FTP Protocol",
             "value": "ftp://ftp.pride.ebi.ac.uk/pride/data/archive/2023/07/PXD041327/sdrf.tsv"}]},
    ]
    proj = {"accession": "PXD041327", "organisms": [{"name": "Homo sapiens", "accession": "9606"}]}
    b = parse_pride_project(proj, files)
    assert b.deposited_sdrf == "sdrf.tsv"                      # bare name detected (no PXD prefix)
    assert b.deposited_sdrf_url == "https://ftp.pride.ebi.ac.uk/pride/data/archive/2023/07/PXD041327/sdrf.tsv"


def test_no_sdrf_gives_none_url():
    from sdrf_agentic_annotator.fetcher import parse_pride_project
    b = parse_pride_project({"accession": "X"}, [{"fileName": "a.raw"}])
    assert b.deposited_sdrf is None and b.deposited_sdrf_url is None
