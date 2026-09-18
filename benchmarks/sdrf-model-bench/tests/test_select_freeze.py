import pytest

from sdrf_model_bench.freeze import extract_methods, has_deposited_sdrf, pride_quality, raw_file_names
from sdrf_model_bench.sdrf_io import read_sdrf
from sdrf_model_bench.select import pick_balanced, quant_type, truth_ok


def qt(label, acq="NT=Data-Dependent Acquisition;AC=PRIDE:0000627"):
    return quant_type(*read_sdrf(f"source name\tcomment[label]\tcomment[proteomics data acquisition method]\n"
                                 f"s\t{label}\t{acq}\n"))


def test_quant_type():
    assert qt("AC=MS:1002616;NT=TMT126") == "TMT"
    assert qt("AC=MS:1002038;NT=label free sample") == "LFQ"
    assert qt("label free sample", "NT=Data-Independent Acquisition;AC=PRIDE:0000450") == "DIA"
    assert qt("label free sample", "NT=SWATH MS") == "DIA"
    assert qt("SILAC heavy") is None


def test_truth_ok_limits_rows():
    head = "source name\tcomment[data file]\n"
    assert truth_ok(head + "s\ta.raw\n")
    assert not truth_ok(head + "".join(f"s{i}\tf{i}.raw\n" for i in range(61)))
    assert not truth_ok("source name\tx\ns\ty\n")


def test_pride_quality():
    full = {k: [{"name": "x"}] for k in ("organisms", "organismParts", "diseases", "instruments",
                                         "identifiedPTMStrings", "quantificationMethods")}
    full.update(sampleProcessingProtocol="p" * 200, dataProcessingProtocol="d" * 200)
    assert pride_quality(full) == 1.0
    assert pride_quality({"organisms": [{"name": "x"}]}) == pytest.approx(1 / 8)


def test_files_helpers():
    files = [{"fileName": "a.raw", "fileCategory": {"value": "RAW"}},
             {"fileName": "b.txt", "fileCategory": {"value": "OTHER"}},
             {"fileName": "x.sdrf.tsv", "fileCategory": {"value": "EXPERIMENTAL DESIGN"}}]
    assert raw_file_names(files) == ["a.raw"]
    assert has_deposited_sdrf(files)


def test_extract_methods_prefers_methods_and_sample_legends():
    xml = """<article><body>
      <sec><title>Introduction</title><p>Background.</p></sec>
      <sec><title>Materials and Methods</title><p>Cells were lysed. TMT labelling.</p></sec>
      <sec><title>Results</title><p>Stuff.</p>
        <fig><caption><p>Samples from 3 patients per condition.</p></caption></fig>
        <fig><caption><p>A volcano plot.</p></caption></fig></sec>
    </body></article>"""
    text = extract_methods(xml)
    assert "Cells were lysed" in text and "3 patients" in text
    assert "Background" not in text and "volcano" not in text


def test_pick_balanced_is_stratified_and_seeded():
    pool = [{"accession": f"P{t}{i}", "qtype": t, "quality": i / 10, "non_human": i % 3 == 0,
             "cell_line_only": False} for t in ("TMT", "LFQ", "DIA") for i in range(9)]
    a, b = pick_balanced(pool, seed=7), pick_balanced(pool, seed=7)
    assert [x["accession"] for x in a] == [x["accession"] for x in b]
    assert len(a) == 12
    for t in ("TMT", "LFQ", "DIA"):
        tiers = sorted(x["tier"] for x in a if x["qtype"] == t)
        assert tiers == ["poor", "poor", "rich", "rich"]
    assert sum(x["non_human"] for x in a) >= 3
