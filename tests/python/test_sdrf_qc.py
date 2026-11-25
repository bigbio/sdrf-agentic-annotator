import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))
import sdrf_qc  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "qc"
QC = DATA / "PXDQC01"
SDRF = DATA / "PXDQC01.sdrf.tsv"


def test_reads_one_record_per_data_file():
    files = sdrf_qc.read_qc(QC)
    assert sorted(files) == ["run1.raw", "run2.raw", "run3.raw"]
    assert files["run1.raw"]["instrument_model"] == "Orbitrap Exploris 480"
    assert files["run1.raw"]["dissociation"] == [("MS:1000422", "beam-type collision-induced dissociation", 900)]
    assert files["run1.raw"]["collision_energy"] == ["30 eV"]
    assert files["run1.raw"]["acquisition_method"] == ("Data-dependent acquisition", "PRIDE:0000627")
    assert files["run1.raw"]["precursor_tolerance_ppm"] == 5.2


def test_exploratory_evidence_is_not_kept():
    rec = sdrf_qc.read_qc(QC)["run1.raw"]
    assert not any("tmt" in k or "shift" in k for k in rec)


def test_cell_larger_than_csv_default_limit(tmp_path):
    d = tmp_path / "qc" / "1"
    d.mkdir(parents=True)
    src = (QC / "1" / "annotations.tsv").read_text().splitlines()
    big = json.dumps([{"delta_mass_da": 0.98}] * 8000)  # > 131072 characters
    src.append("\t".join(["run1.raw", "putative_modification_mass_shifts", big, "inferred", "", "", "", ""]))
    (d / "annotations.tsv").write_text("\n".join(src) + "\n")
    assert sdrf_qc.read_qc(tmp_path / "qc")["run1.raw"]["instrument_model"] == "Orbitrap Exploris 480"


def test_consensus_reports_disagreement_with_counts():
    s = sdrf_qc.summarise(sdrf_qc.read_qc(QC))
    inst = s["instrument_model"]
    assert inst["value"] == "Orbitrap Exploris 480" and inst["support"] == 2 and inst["total"] == 3
    assert inst["others"] == {"Q Exactive HF": 1}
    assert s["acquisition_method"]["evidence"] == "inferred"
    assert s["dissociation"]["value"] == "beam-type collision-induced dissociation (MS:1000422)"


def test_same_instrument_ignores_vendor_words_but_not_models():
    same = sdrf_qc.same_instrument
    assert same("NT=Orbitrap Exploris 480;AC=MS:1003028", "Exploris 480")
    assert same("NT=Q Exactive HF;AC=MS:1002523", "Q Exactive HF")
    assert not same("NT=Q Exactive;AC=MS:1001911", "Q Exactive HF")
    assert not same("NT=Q Exactive HF;AC=MS:1002523", "Q Exactive HF-X")


def test_compare_flags_contradictions_by_file():
    found = sdrf_qc.compare(SDRF, sdrf_qc.read_qc(QC))
    kinds = {(f["column"], f["file"]) for f in found["mismatches"]}
    assert ("comment[instrument]", "run1.raw") in kinds  # SDRF Q Exactive HF, raw Exploris 480
    assert ("comment[dissociation method]", "run2.raw") in kinds  # SDRF CID, raw HCD
    assert ("comment[proteomics data acquisition method]", "run1.raw") in kinds  # SDRF DIA, raw DDA
    assert ("comment[instrument]", "run3.raw") not in kinds
    assert found["matched_files"] == 3 and found["sdrf_files"] == 4  # run4.raw has no QC


def test_markdown_sections_hold_rules_and_values():
    files = sdrf_qc.read_qc(QC)
    sheet = sdrf_qc.sheet_markdown(files)
    assert sheet.startswith("## Raw-file QC")
    assert "Orbitrap Exploris 480" in sheet and "observed" in sheet and "not the search tolerance" in sheet
    checks = sdrf_qc.checks_markdown(SDRF, files)
    assert "comment[instrument]" in checks and "run1.raw" in checks


def test_no_qc_files_gives_empty_output(tmp_path):
    assert sdrf_qc.read_qc(tmp_path / "missing") == {}
    assert sdrf_qc.sheet_markdown({}) == ""
    assert sdrf_qc.checks_markdown(SDRF, {}) == ""


def test_cli_never_fails(tmp_path, capsys):
    assert sdrf_qc.main(["sheet", str(tmp_path / "missing")]) == 0
    assert sdrf_qc.main(["compare", str(QC), str(tmp_path / "missing.sdrf.tsv")]) == 0


def test_hcd_written_without_accession_matches_beam_type(tmp_path):
    rows = list(csv.reader(open(SDRF), delimiter="\t"))
    i = rows[0].index("comment[dissociation method]")
    for r in rows[1:]:
        r[i] = "NT=HCD"
    p = tmp_path / "x.sdrf.tsv"
    csv.writer(open(p, "w", newline=""), delimiter="\t", lineterminator="\n").writerows(rows)
    found = sdrf_qc.compare(p, sdrf_qc.read_qc(QC))
    assert not [m for m in found["mismatches"] if m["column"] == "comment[dissociation method]"]


def test_full_hcd_name_is_not_read_as_cid(tmp_path):
    rows = list(csv.reader(open(SDRF), delimiter="\t"))
    i = rows[0].index("comment[dissociation method]")
    for r in rows[1:]:
        r[i] = "NT=higher energy beam-type collision-induced dissociation"
    p = tmp_path / "x.sdrf.tsv"
    csv.writer(open(p, "w", newline=""), delimiter="\t", lineterminator="\n").writerows(rows)
    found = sdrf_qc.compare(p, sdrf_qc.read_qc(QC))
    assert not [m for m in found["mismatches"] if m["column"] == "comment[dissociation method]"]
