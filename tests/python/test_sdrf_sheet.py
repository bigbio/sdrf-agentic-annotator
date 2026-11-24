"""Tests for bin/sdrf_sheet.py. Run with:
    PYTHONPATH=bin python -m pytest tests/python/test_sdrf_sheet.py
"""
import sdrf_sheet

PAPER = """Title of the paper

Introduction
Proteins matter. We used nothing here.

Materials and Methods
Cell culture
HeLa cells were grown in DMEM and treated with drug X for 24 h.

LC-MS/MS analysis
Peptides were separated on a 120 min gradient and analysed on an Orbitrap Exploris 480 in DDA mode.

Results
We identified 5000 proteins in HeLa cells.

References
1. Someone et al.
"""


def test_methods_excerpt_keeps_methods_only():
    out = sdrf_sheet.methods_excerpt(PAPER)
    assert out["found"] is True
    assert "Orbitrap Exploris 480 in DDA mode" in out["text"]
    assert "treated with drug X" in out["text"]
    assert "5000 proteins" not in out["text"]
    assert "Proteins matter" not in out["text"]


def test_methods_excerpt_no_heading():
    assert sdrf_sheet.methods_excerpt("") == {"found": False, "headings": [], "text": ""}
    out = sdrf_sheet.methods_excerpt("Just a short abstract about proteins in cells.")
    assert out["found"] is False and out["text"] == ""


def test_methods_excerpt_cut():
    filler = "Samples were handled with care in the cold room for a long time. " * 400
    text = "Methods\n" + filler + "Precursor tolerance was 10 ppm. Proteins were digested with trypsin.\n" + filler + "\nResults\nx"
    out = sdrf_sheet.methods_excerpt(text, limit=6000)
    assert len(out["text"]) <= 6000
    assert "10 ppm" in out["text"]
    assert "trypsin" in out["text"]


def _by_field(items):
    return {i["field"]: i for i in items}


def test_search_settings():
    s = "Precursor mass tolerance was set to 10 ppm and fragment tolerance to 0.02 Da, allowing up to two missed cleavages."
    got = _by_field(sdrf_sheet.search_settings(s))
    assert got["precursor_tolerance"]["value"] == "10 ppm"
    assert got["fragment_tolerance"]["value"] == "0.02 Da"
    assert got["missed_cleavages"]["value"] == "2"
    for item in got.values():
        assert item["sentence"] == s
        assert item["confirm"] is True and item["basis"] == "text"


def test_search_settings_mmu_and_fractions():
    got = _by_field(sdrf_sheet.search_settings(
        "MS/MS tolerance was 20 mmu. The peptides were fractionated into 12 fractions by high-pH reversed phase."))
    assert got["fragment_tolerance"]["value"] == "20 mmu"
    assert got["fractions"]["value"] == "12"


def test_filename_design():
    files = ["2019_HeLa_ctrl_R1_F01.raw", "2019_HeLa_ctrl_R2_F02.raw", "2019_HeLa_drug_R1_F01.raw", "2019_HeLa_drug_R2_F02.raw"]
    out = sdrf_sheet.filename_design(files)
    kinds = {p["kind"]: sorted(p["values"]) for p in out["positions"]}
    assert kinds["condition"] == ["ctrl", "drug"]
    assert kinds["replicate"] == ["R1", "R2"]
    assert kinds["fraction"] == ["F01", "F02"]
    assert "2019" in out["dropped"] and "HeLa" in out["dropped"]


def test_filename_design_timestamps_and_caps():
    files = [f"20231105{h:06d}_s{i}_c{i % 40}_x{i % 30}_y{i % 20}_z{i % 25}_a{i % 15}_b{i % 14}_d{i % 13}_e{i % 17}.raw"
             for i, h in enumerate(range(100000, 100300))]
    out = sdrf_sheet.filename_design(files)
    assert len(out["positions"]) <= 8
    assert all(len(p["values"]) <= 12 for p in out["positions"])
    assert not any(v.isdigit() and len(v) >= 6 for p in out["positions"] for v in p["values"])
