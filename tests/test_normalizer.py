from sdrf_harness.normalizer import normalize_sdrf


def _cols(text):
    return text.splitlines()[0].split("\t")


def test_adds_technology_type_and_acquisition():
    text = ("source name\tassay name\tcomment[data file]\n"
            "s1\trun 1\ta.raw\n")
    out = normalize_sdrf(text, acquisition="DIA")
    cols = _cols(out)
    assert "technology type" in cols
    assert "comment[proteomics data acquisition method]" in cols
    # order: assay name -> technology type -> acquisition method
    assert cols.index("technology type") == cols.index("assay name") + 1
    assert cols.index("comment[proteomics data acquisition method]") == cols.index("technology type") + 1
    row = out.splitlines()[1].split("\t")
    assert row[cols.index("technology type")] == "proteomic profiling by mass spectrometry"
    assert row[cols.index("comment[proteomics data acquisition method]")] == \
        "NT=Data-independent acquisition;AC=PRIDE:0000450"


def test_strips_whitespace_and_pads_ragged():
    text = "source name\tassay name\tcomment[data file]\ns1 \trun 1\n"
    out = normalize_sdrf(text)
    row = out.splitlines()[1].split("\t")
    assert row[0] == "s1"                      # trailing space stripped
    assert len(row) == len(_cols(out))         # padded to header width


def test_fixes_fraction_identifier_not_applicable():
    text = ("source name\tassay name\tcomment[proteomics data acquisition method]\t"
            "technology type\tcomment[fraction identifier]\tcomment[data file]\n"
            "s1\trun 1\tNT=Data-dependent acquisition;AC=PRIDE:0000627\t"
            "proteomic profiling by mass spectrometry\tnot applicable\ta.raw\n")
    out = normalize_sdrf(text)
    cols = _cols(out)
    row = out.splitlines()[1].split("\t")
    assert row[cols.index("comment[fraction identifier]")] == "1"


def test_idempotent_when_already_complete():
    text = ("source name\tassay name\ttechnology type\t"
            "comment[proteomics data acquisition method]\tcomment[data file]\n"
            "s1\trun 1\tproteomic profiling by mass spectrometry\t"
            "NT=Data-dependent acquisition;AC=PRIDE:0000627\ta.raw\n")
    assert normalize_sdrf(text) == text
