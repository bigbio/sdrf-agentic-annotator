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


# ---------------------------------------------------------------- term matches

from pathlib import Path

ONTOLOGIES = Path(__file__).resolve().parents[1] / "data" / "ontologies"
TEXT = ("HeLa and PC-3 cells and primary fibroblasts were used. Liver tissue and serum came from patients with breast carcinoma. "
        "Methionine oxidation was a variable modification. Spectra were acquired on an Orbitrap Exploris 480.")


def _terms():
    terms, reason = sdrf_sheet.load_terms(str(ONTOLOGIES))
    assert reason is None
    terms["cell_line"] = [{"label": "HeLa", "accession": None}, {"label": "PC-3", "accession": None}]
    return terms


def _labels(matches, category):
    return {m["label"].lower(): m for m in matches.get(category, [])}


def test_term_matches_whole_word():
    m = sdrf_sheet.term_matches(TEXT, _terms())
    assert set(_labels(m, "cell_line")) == {"hela", "pc-3"}
    assert _labels(m, "organism_part")["liver"]["accession"] == "uberon:0002107"
    assert _labels(m, "disease")["breast carcinoma"]["accession"] == "mondo:0007254"
    assert "liver" not in _labels(m, "disease")  # imported uberon term in mondo is not a disease
    assert _labels(m, "modification")["oxidation"]["accession"] == "unimod:35"
    assert _labels(m, "cell_type")["fibroblast"]["count"] == 1
    inst = _labels(m, "instrument")
    assert "orbitrap exploris 480" in inst and "orbitrap" not in inst  # longest match wins
    assert inst["orbitrap exploris 480"]["sentence"].startswith("Spectra were acquired")


def test_short_labels_need_capitals():
    assert "all" not in _labels(sdrf_sheet.term_matches("all samples were ca. 10 years old", _terms()), "disease")
    hit = sdrf_sheet.term_matches("Children with ALL were included.", _terms())
    assert "all" in _labels(hit, "disease")


def test_stop_list():
    m = sdrf_sheet.term_matches("Each cell sample was a control tissue protein from serum.", _terms())
    found = {label for cat in m.values() for label in _labels({"x": cat}, "x")}
    assert "serum" in found
    assert not found & {"cell", "tissue", "protein", "control", "sample"}


def test_load_terms_missing_dir(tmp_path):
    for d in (None, str(tmp_path / "nope")):
        terms, reason = sdrf_sheet.load_terms(d)
        assert terms == {} and reason


def test_search_settings_ignores_scan_range():
    s = "MS/MS product ion scan from 200 to 1250 Da was followed by a survey scan of 100-1500 Da."
    assert sdrf_sheet.search_settings(s) == []


def test_single_word_labels_need_corpus_use():
    terms = {"organism_part": [{"label": "tube", "accession": "uberon:1"}, {"label": "liver", "accession": "uberon:2"},
                               {"label": "bone marrow", "accession": "uberon:3"}]}
    text = "The liver and bone marrow were put in a tube."
    m = sdrf_sheet.term_matches(text, terms, known={"organism_part": {"liver"}})
    assert set(_labels(m, "organism_part")) == {"liver", "bone marrow"}
    assert set(_labels(sdrf_sheet.term_matches(text, terms), "organism_part")) == {"liver", "bone marrow", "tube"}


# ---------------------------------------------------------------- corpus index and similar SDRFs

import csv
import subprocess
import sys

CORPUS = Path(__file__).resolve().parents[1] / "data" / "corpus"
BIN = Path(__file__).resolve().parents[2] / "bin"


def _index(tmp_path):
    out = tmp_path / "index.tsv"
    subprocess.run([sys.executable, str(BIN / "build_corpus_index.py"), str(CORPUS), str(out)], check=True)
    return out


def test_build_index(tmp_path):
    rows = {r["accession"]: r for r in csv.DictReader(open(_index(tmp_path)), delimiter="\t")}
    assert set(rows) == {"PXD000101", "PXD000102", "PXD000103"}  # sandbox left out
    r = rows["PXD000101"]
    assert r["organism"] == "Homo sapiens" and r["instrument"] == "Orbitrap Exploris 480"
    assert r["label"] == "label free sample" and r["cell_line"] == "HeLa"
    assert r["modification"] == "Oxidation"
    assert "comment[instrument]" in r["columns"].split("|")


FACTS = {"organism": {"homo sapiens"}, "instrument": {"orbitrap exploris 480"}, "label": {"label free sample"}}


def test_similar_requires_core_match(tmp_path):
    facts = dict(FACTS, label={"silac"})
    assert sdrf_sheet.similar_sdrfs(str(_index(tmp_path)), facts, str(CORPUS)) == []


def test_similar_ranks_by_shared_biology(tmp_path):
    facts = dict(FACTS, cell_line={"hela"}, disease={"cervical adenocarcinoma"})
    got = sdrf_sheet.similar_sdrfs(str(_index(tmp_path)), facts, str(CORPUS))
    assert [g["accession"] for g in got] == ["PXD000101", "PXD000102"]
    assert set(got[0]["shared"]) >= {"cell_line", "disease"}
    assert got[0]["header"][0] == "source name" and len(got[0]["rows"]) == 2
    no_root = sdrf_sheet.similar_sdrfs(str(_index(tmp_path)), facts, None)
    assert no_root[0]["header"][0] == "source name" and no_root[0]["rows"] == []


def test_corpus_terms(tmp_path):
    cell_lines, known = sdrf_sheet.corpus_terms(str(_index(tmp_path)))
    assert {"label": "HeLa", "accession": None} in cell_lines
    assert "cervix" in known["organism_part"] and "oxidation" in known["modification"]
    assert "orbitrap exploris 480" in known["instrument"]
    assert sdrf_sheet.corpus_terms(None) == ([], None)


def test_gzipped_index(tmp_path):
    out = tmp_path / "index.tsv.gz"
    subprocess.run([sys.executable, str(BIN / "build_corpus_index.py"), str(CORPUS), str(out)], check=True)
    assert out.read_bytes()[:2] == b"\x1f\x8b"  # really gzip, not plain text under a .gz name
    facts = dict(FACTS, cell_line={"hela"})
    assert [g["accession"] for g in sdrf_sheet.similar_sdrfs(str(out), facts, None)][0] == "PXD000101"
    assert sdrf_sheet.corpus_terms(str(out))[1]["cell_line"] == {"hela"}
