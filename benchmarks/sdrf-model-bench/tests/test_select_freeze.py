import pytest

from sdrf_model_bench.freeze import extract_methods, has_deposited_sdrf, pride_quality, raw_file_names
from sdrf_model_bench.sdrf_io import read_sdrf
from sdrf_model_bench.select import pick_balanced, quant_type, truth_ok


def qt(label, acq="NT=Data-Dependent Acquisition;AC=PRIDE:0000627"):
    return quant_type(*read_sdrf(f"source name\tcomment[label]\tcomment[proteomics data acquisition method]\n"
                                 f"s\t{label}\t{acq}\n"))


def test_quant_type():
    tmt = "source name\tcomment[label]\ns1\tAC=MS:1002616;NT=TMT126\ns2\tAC=MS:1002617;NT=TMT127\n"
    assert quant_type(*read_sdrf(tmt)) == "TMT"
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
      <sec><title>Materials and Methods</title><p>Cells were lysed. TMT labelling. y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y y</p></sec>
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


def test_tmt_needs_channel_level_rows():
    one_label = "source name\tcomment[label]\ns1\tNT=TMT6plex\ns2\tNT=TMT6plex\n"
    two = "source name\tcomment[label]\ns1\tNT=TMT126\ns2\tNT=TMT127\n"
    assert quant_type(*read_sdrf(one_label)) is None
    assert quant_type(*read_sdrf(two)) == "TMT"


def test_community_sdrf_is_not_a_submitter_sdrf():
    files = [{"fileName": "PXD1_community_annotated.sdrf.tsv", "fileCategory": {"value": "EXPERIMENTAL DESIGN"}}]
    assert not has_deposited_sdrf(files)


def test_license_rules():
    from sdrf_model_bench.freeze import redistributable

    assert redistributable("cc by") and redistributable("cc by-nc") and redistributable("cc0")
    assert not redistributable("cc by-nc-nd") and not redistributable("cc by-nd") and not redistributable("")


def test_row_cap_is_per_quant_type(tmp_path):
    from sdrf_model_bench.select import iter_candidates

    def write(acc, label, n):
        d = tmp_path / acc
        d.mkdir()
        rows = "".join(f"s{i}\tf{i // 10}.raw\tNT={label}{126 + i % 10}\n" for i in range(n))
        (d / f"{acc}.sdrf.tsv").write_text("source name\tcomment[data file]\tcomment[label]\n" + rows)

    write("PXD000010", "TMT", 90)
    write("PXD000011", "TMT", 101)
    write("PXD000012", "label free sample", 61)
    assert [c["accession"] for c in iter_candidates(tmp_path)] == ["PXD000010"]


def test_extract_methods_requires_a_methods_section_and_keeps_word_breaks():
    no_methods = "<article><body><sec><title>Introduction</title><p>Only intro.</p></sec></body></article>"
    assert extract_methods(no_methods) == ""
    xml = ("<article><body><sec><title>Methods</title><sec><title>Animals</title><p>Mice." + " z" * 300
           + "</p></sec></sec></body></article>")
    assert "Methods Animals Mice." in extract_methods(xml)


def test_nested_methods_are_not_duplicated():
    xml = ("<article><body><sec><title>Methods</title><sec><title>Proteomics methods</title>"
           "<p>LC-MS once." + " w" * 300 + "</p></sec></sec></body></article>")
    assert extract_methods(xml).count("LC-MS once.") == 1


def test_methods_heading_must_be_a_methods_section():
    from sdrf_model_bench.freeze import METHODS_RE

    for ok in ("Methods", "Materials and Methods", "2. Materials & methods", "EXPERIMENTAL PROCEDURES",
               "Experimental Section", "STAR Methods", "Online Methods", "Methods and materials"):
        assert METHODS_RE.search(ok), ok
    for bad in ("A flow cytometry based method to monitor growth", "Methodology comparison", "Results"):
        assert not METHODS_RE.search(bad), bad


def test_empty_methods_heading_takes_following_siblings():
    xml = ("<article><body><sec><title>Introduction</title><p>Intro.</p></sec>"
           "<sec><title>EXPERIMENTAL PROCEDURES</title></sec>"
           "<sec><title>Materials</title><p>HeLa pellets. x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x x</p></sec>"
           "<sec><title>Mass spectrometry</title><p>Orbitrap.</p></sec>"
           "<sec><title>Results</title><p>We found.</p></sec></body></article>")
    text = extract_methods(xml)
    assert "HeLa pellets." in text and "Orbitrap." in text
    assert "We found." not in text and "Intro." not in text
