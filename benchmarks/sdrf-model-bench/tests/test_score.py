import pytest

from sdrf_model_bench.score import (
    file_key, mods_agreement, score_deterministic, term_agreement, tolerance_agreement,
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
    assert term_agreement(t, "breast carcinoma") == 0.5
    assert term_agreement(t, "NT=breast carcinoma;AC=EFO:9999999") == 0.5
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
