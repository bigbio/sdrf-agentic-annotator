import pytest

from sdrf_model_bench.score import (
    file_key,
    mods_agreement,
    score_deterministic,
    term_agreement,
    tolerance_agreement,
)
from sdrf_model_bench.sdrf_io import parse_term, read_sdrf

H = ("source name\tcharacteristics[organism]\tcharacteristics[disease]\tassay name\t"
     "comment[data file]\tcomment[label]\tcomment[modification parameters]\t"
     "comment[modification parameters]\tcomment[precursor mass tolerance]\n")


def row(i, organism="homo sapiens", disease="NT=breast carcinoma;AC=EFO:0000305",
        label="AC=MS:1002038;NT=label free sample", tol="10 ppm", mods=None):
    mods = mods or ["NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed",
                    "NT=Oxidation;AC=UNIMOD:35;TA=M;MT=Variable"]
    return f"s{i}\t{organism}\t{disease}\trun{i}\tfile{i}.raw\t{label}\t{mods[0]}\t{mods[1]}\t{tol}\n"


TRUTH = H + row(1) + row(2)


def test_read_sdrf_keeps_duplicate_columns():
    header, rows = read_sdrf(TRUTH)
    assert header.count("comment[modification parameters]") == 2
    assert len(rows) == 2


def test_parse_term():
    assert parse_term("NT=Breast Carcinoma;AC=efo_0000305") == ("breast carcinoma", "EFO:0000305")
    assert parse_term("Homo sapiens") == ("homo sapiens", "")


def test_term_agreement_levels():
    t = "NT=breast carcinoma;AC=EFO:0000305"
    assert term_agreement(t, t) == 1.0
    assert term_agreement(t, "breast carcinoma") == 1.0  # style: same term, accession omitted
    assert term_agreement(t, "NT=breast carcinoma;AC=EFO:9999999") == 0.5  # same label, conflicting accession
    assert term_agreement(t, "NT=lung carcinoma;AC=EFO:0001071") == 0.0
    assert term_agreement("homo sapiens", "Homo sapiens") == 1.0


def test_tolerance_and_mods():
    assert tolerance_agreement("10 ppm", "10.0ppm") == 1.0
    assert tolerance_agreement("10 ppm", "0.01 Da") == 0.0
    a = ["NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed"]
    assert mods_agreement(a, ["NT=carbamidomethyl;TA=C;MT=fixed"]) == 1.0
    assert mods_agreement(a, a + ["NT=Oxidation;TA=M;MT=Variable"]) == 0.5


def test_file_key_normalises():
    assert file_key("ftp://x/y/File1.RAW") == file_key("file1.raw") == "file1"
    assert file_key("a.mzML.gz") == "a"


def test_self_score_is_perfect():
    s = score_deterministic(TRUTH, TRUTH, validity=1.0)
    assert s["deterministic"] == pytest.approx(100.0)


def test_missing_rows_and_not_available_are_penalised():
    pred = H + row(1, disease="not available")
    s = score_deterministic(TRUTH, pred, validity=1.0)
    assert s["n_aligned"] == 1
    assert s["completeness"] == pytest.approx(0.5)
    assert s["specificity"] < 1.0
    assert s["deterministic"] < 80


def test_empty_prediction_scores_zero():
    s = score_deterministic(TRUTH, "", validity=0.0)
    assert s["deterministic"] == 0.0


# ---------- triage (PR #24's classes, by deterministic rule) ----------

from sdrf_model_bench.score import (
    accession_report,
    classify_cell,
    ignorant_baseline,
    is_collapsed_plex_reference,
    template_self_declared,
)


def test_classify_match_and_style():
    t = "NT=breast carcinoma;AC=EFO:0000305"
    assert classify_cell("characteristics[disease]", t, t) == (1.0, "match")
    assert classify_cell("characteristics[disease]", t, "Breast Carcinoma") == (1.0, "style")
    assert classify_cell("characteristics[disease]", "breast carcinoma", t) == (1.0, "style")
    assert classify_cell("comment[instrument]", "NT=Q Exactive HF-X", "NT=Q Exactive HF-X;AC=MS:1002877") == (1.0, "style")


def test_classify_run_wrong_and_curated_richer():
    t = "NT=breast carcinoma;AC=EFO:0000305"
    assert classify_cell("characteristics[disease]", t, "NT=lung carcinoma;AC=EFO:0001071") == (0.0, "run_wrong")
    assert classify_cell("characteristics[disease]", t, "not available") == (0.0, "curated_richer")
    assert classify_cell("characteristics[disease]", t, "") == (0.0, "curated_richer")


def test_classify_curated_wrong_malformed_reference_accession():
    # reference accession without an ontology prefix (PXD037221's 'AC=1001251'): labels agree -> credit
    assert classify_cell("comment[cleavage agent details]", "NT=Trypsin;AC=1001251",
                         "NT=Trypsin;AC=MS:1001251") == (1.0, "curated_wrong")
    # labels disagree and the reference is malformed -> cannot be scored
    assert classify_cell("comment[cleavage agent details]", "NT=Trypsin;AC=1001251",
                         "NT=Lys-C;AC=MS:1001309") == (None, "curated_unscorable")


def test_classify_tolerance_unit_mismatch_is_unscorable():
    assert classify_cell("comment[fragment mass tolerance]", "831 ppm", "1 Da") == (None, "curated_unscorable")
    assert classify_cell("comment[fragment mass tolerance]", "0.02 Da", "0.02 Da") == (1.0, "match")
    assert classify_cell("comment[fragment mass tolerance]", "0.02 Da", "0.5 Da") == (0.0, "run_wrong")


def test_classify_run_richer_when_reference_is_na():
    assert classify_cell("characteristics[disease]", "not available", "NT=x;AC=EFO:1") == (None, "run_richer")
    assert classify_cell("characteristics[disease]", "not available", "not available") == (None, "match")


def test_score_records_triage_counts():
    pred = H + row(1, disease="breast carcinoma") + row(2, disease="NT=lung carcinoma;AC=EFO:0001071")
    s = score_deterministic(TRUTH, pred, validity=1.0)
    assert s["triage"]["style"] >= 1
    assert s["triage"]["run_wrong"] >= 1
    assert "match" in s["triage"]


def test_collapsed_plex_reference_aligns_on_file_and_scores_run_level_fields():
    hdr = ("source name\tcharacteristics[organism]\tassay name\tcomment[data file]\tcomment[label]\t"
           "comment[instrument]\tcomment[fraction identifier]\tcomment[technical replicate]\n")
    truth = hdr + "s1\thomo sapiens\trun1\trun1.raw\tTMT10\tNT=Q Exactive;AC=MS:1001911\t1\t1\n"
    pred = hdr + "".join(f"s1-{ch}\thomo sapiens\trun1-{ch}\trun1.raw\t{ch}\tNT=Q Exactive;AC=MS:1001911\t1\t1\n"
                         for ch in ("TMT126", "TMT127N", "TMT128C"))
    assert is_collapsed_plex_reference(*read_sdrf(truth))
    s = score_deterministic(truth, pred, validity=1.0)
    assert s["n_aligned"] == 1
    assert "collapsed_plex" in s["reference_defects"]
    assert s["field_accuracy"]["comment[instrument]"] == 1.0
    assert "characteristics[organism]" not in s["field_accuracy"]  # sample-level: unknowable from a collapsed reference
    assert s["deterministic"] > 60


def test_accession_report_classifies_malformed_and_unverified():
    pred = H + row(1, disease="NT=breast carcinoma;AC=EFO:0000305") + row(2, disease="NT=x;AC=0000305")
    rep = accession_report(pred, resolver=None)
    assert rep["malformed"] == 1
    assert rep["total"] >= 5
    assert rep["verified"] == 0 and rep["unverified"] == rep["total"] - 1
    rep = accession_report(pred, resolver=lambda acc: acc.startswith("UNIMOD:"))
    assert rep["verified"] == 4  # the two UNIMOD mods on each of two rows


def test_template_self_declared():
    assert template_self_declared(TRUTH) is False
    hdr2 = H.rstrip("\n") + "\tcomment[sdrf template]\n"
    assert template_self_declared(hdr2 + row(1).rstrip("\n") + "\tNT=ms-proteomics;VV=v1.1.0\n") is True


def test_ignorant_baseline_uses_the_same_rules():
    assert 0 < ignorant_baseline(TRUTH) < 100


def test_rescore_deterministic_keeps_validity_and_judge(tmp_path):
    import json

    from sdrf_model_bench.scoring_run import rescore_deterministic
    (tmp_path / "truth").mkdir()
    (tmp_path / "truth" / "PXD1.reference.tsv").write_text(TRUTH)
    run = tmp_path / "m" / "PXD1__ms-off__r1"
    run.mkdir(parents=True)
    (run / "sdrf.tsv").write_text(TRUTH)
    (run / "score.json").write_text(json.dumps({"validity": 0.5, "judge": 40.0, "deterministic": 1.0, "headline": 1.0,
                                                 "cost_usd": 2.0}))
    rec = rescore_deterministic(run, tmp_path)
    assert rec["validity"] == 0.5 and rec["judge"] == 40.0 and rec["cost_usd"] == 2.0
    assert rec["deterministic"] == pytest.approx(90.0)  # perfect except validity 0.5 * 0.20
    assert rec["headline"] == pytest.approx(0.8 * 90.0 + 0.2 * 40.0)


def test_silac_reference_aligns_on_file_and_channel():
    hdr = ("source name\tcharacteristics[organism]\tassay name\tcomment[data file]\tcomment[label]\t"
           "comment[instrument]\tcomment[fraction identifier]\tcomment[technical replicate]\n")
    truth = hdr + ("h\thomo sapiens\trun1-H\trun1.raw\tSILAC heavy\tNT=Q Exactive;AC=MS:1001911\t1\t1\n"
                   "l\thomo sapiens\trun1-L\trun1.raw\tSILAC light\tNT=Q Exactive;AC=MS:1001911\t1\t1\n")
    pred = hdr + ("l\thomo sapiens\trun1-L\trun1.raw\tSILAC light\tNT=Q Exactive;AC=MS:1001911\t1\t1\n"
                  "h\thomo sapiens\trun1-H\trun1.raw\tSILAC heavy\tNT=Q Exactive;AC=MS:1001911\t1\t1\n")
    s = score_deterministic(truth, pred, validity=1.0)
    assert s["n_aligned"] == 2
    assert s["field_accuracy"]["comment[label]"] == 1.0  # order in the file must not matter


def test_reference_shared_validator_errors_do_not_count(tmp_path):
    import json

    from sdrf_model_bench.scoring_run import score_run
    from sdrf_model_bench.validator import ValidationResult
    truth = "source name\tcomment[data file]\tcomment[label]\nS1\ta.raw\tSILAC light\nS1\ta.raw\tSILAC heavy\n"
    (tmp_path / "evidence" / "PX1").mkdir(parents=True)
    (tmp_path / "evidence" / "PX1" / "meta.json").write_text(json.dumps({"templates": ["ms-proteomics"]}))
    (tmp_path / "truth").mkdir()
    (tmp_path / "truth" / "PX1.reference.tsv").write_text(truth)
    run = tmp_path / "out" / "m" / "PX1__ms-off__r1"
    run.mkdir(parents=True)
    (run / "sdrf.tsv").write_text(truth)
    (run / "usage.json").write_text("{}")
    shared = "Duplicate (source name, assay name) in row 2"

    def validate(path, templates):
        return ValidationResult(errors=[shared] + (["other problem"] if path.name == "sdrf.tsv" else []))

    rec = score_run(run, tmp_path, validate)
    assert rec["reference_shared_errors"] == 1
    assert rec["validity"] == 0.9  # only the error the reference does not share counts
