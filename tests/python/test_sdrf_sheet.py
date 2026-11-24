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
    cell_lines, known = sdrf_sheet.corpus_terms(str(_index(tmp_path)), min_datasets=1, min_cell_line=1)
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
    assert sdrf_sheet.corpus_terms(str(out), min_datasets=1, min_cell_line=1)[1]["cell_line"] == {"hela"}


# ---------------------------------------------------------------- render and command line

import json

SECTIONS = ["## 1. Methods excerpt", "## 2. Term matches", "## 3. Search settings", "## 4. Design from file names",
            "## 5. Similar SDRFs"]


def _big_sheet():
    long = " ".join(f"Sentence {i} about trypsin digestion at 10 ppm." for i in range(800))
    return {
        "accession": "PXD000001",
        "methods": {"found": True, "headings": ["Methods"], "text": long},
        "terms": {"organism_part": [{"label": f"part{i}", "accession": f"uberon:{i}", "count": 30 - i,
                                     "sentence": "x" * 300} for i in range(30)]},
        "settings": [sdrf_sheet._setting("precursor_tolerance", "10 ppm", "Precursor tolerance was 10 ppm.")],
        "design": {"positions": [{"index": 2, "kind": "condition", "n_values": 2, "values": ["ctrl", "drug"]}],
                   "dropped": ["2019"], "compared": 4, "files": 4},
        "similar": [{"accession": "PXD000101", "shared": ["organism", "instrument", "label"],
                     "header": ["source name"] * 40, "rows": [["v" * 50] * 40] * 3}],
        "errors": {},
    }


def test_render_cap():
    text = sdrf_sheet.render(_big_sheet(), limit=12000)
    assert len(text) <= 12000
    positions = [text.index(s) for s in SECTIONS]
    assert positions == sorted(positions)
    assert "Precursor tolerance was 10 ppm." in text and "(confirm)" in text
    assert "uberon:0" in text and "part29" not in text  # top terms kept, the tail cut
    assert "ctrl, drug" in text and "PXD000101" in text


def test_label_classes_match_corpus(tmp_path):
    facts = {"organism": {"homo sapiens"}, "instrument": {"orbitrap exploris 480"}, "label": {"tmt"}}
    got = sdrf_sheet.similar_sdrfs(str(_index(tmp_path)), facts, None)
    assert [g["accession"] for g in got] == ["PXD000103"]  # corpus label TMT126 is the TMT class


def _evidence(tmp_path, manuscript):
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "pride.json").write_text(json.dumps({
        "accession": "PXD000001", "title": "HeLa proteome",
        "sampleProcessingProtocol": "HeLa cells were digested with trypsin.",
        "dataProcessingProtocol": "Precursor mass tolerance was 10 ppm."}))
    (ev / "files.json").write_text(json.dumps({"files": ["a_ctrl_R1.raw", "a_drug_R1.raw"], "other_files": []}))
    (ev / "manuscript.txt").write_text(manuscript)
    prefill = tmp_path / "PXD000001.prefill.json"
    prefill.write_text(json.dumps({
        "organism": [{"value": "Homo sapiens"}], "instrument": [{"value": "Orbitrap Exploris 480"}],
        "label": [{"value": "label free sample"}], "files": {"run_files": ["a_ctrl_R1.raw", "a_drug_R1.raw"]}}))
    return ev, prefill


def test_cli_writes_sheet(tmp_path):
    ev, prefill = _evidence(tmp_path, PAPER)
    out = tmp_path / "PXD000001"
    subprocess.run([sys.executable, str(BIN / "sdrf_sheet.py"), str(ev), str(prefill), str(out),
                    "--ontology-dir", str(ONTOLOGIES), "--corpus-index", str(_index(tmp_path))], check=True)
    text = (tmp_path / "PXD000001.sheet.md").read_text()
    data = json.loads((tmp_path / "PXD000001.sheet.json").read_text())
    assert "Orbitrap Exploris 480 in DDA mode" in text  # methods excerpt
    assert "10 ppm" in text  # from the PRIDE protocol when the manuscript does not say it
    assert "ctrl, drug" in text
    assert "HeLa" in {m["label"] for m in data["terms"].get("cell_line", [])}
    assert data["errors"] == {}


def test_cli_never_fails(tmp_path):
    ev, prefill = _evidence(tmp_path, "")
    bad = tmp_path / "ontologies"
    bad.mkdir()
    (bad / "uberon.parquet").write_text("not a parquet file")
    out = tmp_path / "PXD000001"
    r = subprocess.run([sys.executable, str(BIN / "sdrf_sheet.py"), str(ev), str(prefill), str(out),
                        "--ontology-dir", str(bad), "--corpus-index", str(tmp_path / "missing.tsv")])
    assert r.returncode == 0
    text = (tmp_path / "PXD000001.sheet.md").read_text()
    assert "no manuscript methods found" in text
    assert "Term matches" in text and "Not available" in text
    assert (tmp_path / "PXD000001.sheet.json").exists()


def test_tolerance_first_and_main_search():
    s = ("The mass tolerance for precursor ions was set as 20 ppm in First search and 5 ppm in Main search, "
         "and the mass tolerance for fragment ions was set as 0.02 Da.")
    got = {(i["field"], i["value"]) for i in sdrf_sheet.search_settings(s)}
    assert got == {("precursor_tolerance", "20 ppm (first search)"), ("precursor_tolerance", "5 ppm (main search)"),
                   ("fragment_tolerance", "0.02 Da")}


def test_corpus_terms_thresholds(tmp_path):
    index = str(_index(tmp_path))
    # HeLa is used by two corpus datasets, cervix by two, oxidation by two
    lines, known = sdrf_sheet.corpus_terms(index, min_datasets=3, min_cell_line=2)
    assert [t["label"] for t in lines] == ["HeLa"] and "cervix" not in known["organism_part"]
    lines, known = sdrf_sheet.corpus_terms(index, min_datasets=2, min_cell_line=3)
    assert lines == [] and "cervix" in known["organism_part"]


def test_cell_line_name_shape():
    ok = sdrf_sheet.cell_line_name_ok
    assert ok("HeLa") and ok("CHO") and ok("PANC-1") and ok("A549") and ok("MCF 10A")
    assert not ok("pooled") and not ok("27") and not ok("cell line") and not ok("x") and not ok("mixed cells")
    assert not ok("HT")  # two-letter codes match acronyms in methods text


def test_similar_excludes_own_accession(tmp_path):
    facts = dict(FACTS, cell_line={"hela"})
    got = sdrf_sheet.similar_sdrfs(str(_index(tmp_path)), facts, None, exclude="PXD000101")
    assert "PXD000101" not in [g["accession"] for g in got]


def test_instrument_needs_model_name():
    terms = {"instrument": [{"label": "orbitrap", "accession": "ms:1000484"},
                            {"label": "orbitrap exploris 480", "accession": "ms:1003028"}]}
    m = sdrf_sheet.term_matches("Peptides were detected in the Orbitrap.", terms, known={"instrument": {"orbitrap"}})
    assert m.get("instrument", []) == []


# ---------------------------------------------------------------- final review fixes

def _settings(s):
    return {(i["field"], i["value"]) for i in sdrf_sheet.search_settings(s)}


def test_tolerance_named_after_the_number():
    assert _settings("A mass tolerance of 10 ppm for precursors and 0.5 Da for fragments was used.") == {
        ("precursor_tolerance", "10 ppm"), ("fragment_tolerance", "0.5 Da")}
    assert _settings("The tolerance was 4.5 ppm (precursor) and 20 ppm for MS/MS spectra.") == {
        ("precursor_tolerance", "4.5 ppm"), ("fragment_tolerance", "20 ppm")}


def test_isolation_window_is_not_a_tolerance():
    assert _settings("The precursor isolation window was 1.6 Th and the precursor mass window was set to 2 Th.") == set()


def test_quote_contains_the_match():
    lead = "Figure 1 legend: overview of the cohorts, the collection sites and the timing of every sample " * 4
    text = lead + "with samples taken from the venous sinus of each donor."
    m = sdrf_sheet.term_matches(text, {"organism_part": [{"label": "venous sinus", "accession": "uberon:0006615"}]})
    sheet = {"accession": "PXD1", "terms": m}
    assert "venous sinus" in sdrf_sheet.render(sheet).split("venous sinus (uberon:0006615)")[1].split("\n")[0]


def test_cell_line_needs_cell_context_or_code():
    terms = {"cell_line": [{"label": "GEO", "accession": None}, {"label": "Ramos", "accession": None},
                           {"label": "K562", "accession": None}, {"label": "HEL", "accession": None}]}
    text = "Data were deposited in GEO. Ramos cells and K562 were lysed in HEL buffer."
    assert set(_labels(sdrf_sheet.term_matches(text, terms), "cell_line")) == {"ramos", "k562"}


def test_reagent_phrases_are_not_terms():
    terms = {"modification": [{"label": "dimethyl", "accession": "unimod:36"}],
             "organism_part": [{"label": "milk", "accession": "uberon:0001913"},
                               {"label": "blood", "accession": "uberon:0000178"},
                               {"label": "serum", "accession": "uberon:0001977"}]}
    text = ("Cells were frozen in dimethyl sulfoxide and blocked with 5% non-fat milk in medium with fetal bovine serum. "
            "Cells came from a single blood donor.")
    assert sdrf_sheet.term_matches(text, terms) == {}


def test_known_counts_accessions_not_files(tmp_path):
    index = tmp_path / "index.tsv"
    head = "accession\tpath\torganism\tinstrument\tlabel\tcell_line\torganism_part\tdisease\tcell_type\tmodification\tcolumns\n"
    rows = "".join(f"PXD000200\tdatasets/PXD000200/f{i}.sdrf.tsv\tHomo sapiens\tx\tlabel free sample\t\tknee\t\t\t\tsource name\n"
                   for i in range(12))
    index.write_text(head + rows)
    assert "knee" not in sdrf_sheet.corpus_terms(str(index), min_datasets=10)[1]["organism_part"]


def test_few_files_are_conditions_not_runs():
    out = sdrf_sheet.filename_design(["FA257LQ_Control_Slot2_24.raw", "FA257LQ_Yuanwei_Slot2_25.raw"])
    assert {p["kind"] for p in out["positions"]} == {"condition"}
    many = sdrf_sheet.filename_design([f"X_s{i}_ctrl.raw" if i % 2 else f"X_s{i}_drug.raw" for i in range(8)])
    assert {p["values"][0]: p["kind"] for p in many["positions"]}["s0"] == "run"


def test_default_ontology_dir(tmp_path, monkeypatch):
    (tmp_path / "uberon.tsv").write_text("accession\tlabel\tontology\nuberon:0002107\tliver\tuberon\n")
    monkeypatch.setattr(sdrf_sheet, "DEFAULT_ONTOLOGY_DIR", str(tmp_path))
    terms, reason = sdrf_sheet.load_terms(None)
    assert reason is None and terms["organism_part"][0]["label"] == "liver"


def test_tolerances_respectively():
    assert _settings("The mass tolerances were set to 10 ppm and 0.02 Da for precursor and fragment ions, respectively.") == {
        ("precursor_tolerance", "10 ppm"), ("fragment_tolerance", "0.02 Da")}
