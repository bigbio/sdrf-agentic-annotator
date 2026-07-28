import json
from pathlib import Path
from sdrf_harness.fetcher import parse_pride_project, is_annotatable

FIX = Path(__file__).parent / "fixtures"

def test_parse_pride_project_extracts_core_fields():
    proj = json.load(open(FIX / "pride_PXDTEST.json"))
    b = parse_pride_project(proj, proj["_files"])
    assert b.accession == "PXDTEST"
    assert ("Homo sapiens", "9606") in b.organisms
    assert "Q Exactive" in b.instruments
    assert any(f["ext"] == "raw" for f in b.files)

def test_is_annotatable_rejects_peaklist_only():
    from sdrf_harness.models import Bundle
    b = Bundle(accession="X", repository="pride",
               files=[{"name": "a.mgf", "ext": "mgf"}, {"name": "b.mzML", "ext": "mzml"}])
    ok, reason = is_annotatable(b)
    assert not ok and "peak-list" in reason

def test_is_annotatable_accepts_raw():
    from sdrf_harness.models import Bundle
    b = Bundle(accession="X", repository="pride", organisms=[("Homo sapiens", "9606")],
               files=[{"name": "a.raw", "ext": "raw"}])
    ok, _ = is_annotatable(b)
    assert ok
