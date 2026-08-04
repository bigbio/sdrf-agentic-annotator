from sdrf_agentic_annotator.expand import (
    expand,
    group_samples,
    parse_fraction,
    sample_signature,
)


def test_parse_fraction():
    assert parse_fraction("20110811_Ecoli_ActNEG_SXC-frac04.raw") == 4
    assert parse_fraction("sample_F03.raw") == 3
    assert parse_fraction("run_fraction_12.raw") == 12
    assert parse_fraction("plain_run.raw") is None


def test_sample_signature_collapses_fractions_and_reps():
    assert sample_signature("Ecoli_ActNEG_F01.raw") == sample_signature(
        "Ecoli_ActNEG_F12.raw"
    )
    assert sample_signature("cond_A_rep1.raw") == sample_signature("cond_A_rep3.raw")
    # different condition -> different sample
    assert sample_signature("cond_A_F1.raw") != sample_signature("cond_B_F1.raw")


def test_group_samples():
    files = ["A_F01.raw", "A_F02.raw", "A_F03.raw", "B_F01.raw", "B_F02.raw"]
    g = group_samples(files)
    assert len(g) == 2
    assert sum(len(v) for v in g.values()) == 5


def test_expand_one_sample_to_many_files_unique_coordinates():
    header = [
        "source name",
        "characteristics[organism]",
        "characteristics[biological replicate]",
        "assay name",
        "comment[data file]",
        "comment[technical replicate]",
        "comment[fraction identifier]",
    ]
    files = ["cond_F01.raw", "cond_F02.raw", "cond_F03.raw"]
    groups = group_samples(files)
    sample_rows = [
        {
            "source name": "sample 1",
            "characteristics[organism]": "Escherichia coli",
            "characteristics[biological replicate]": "1",
        }
    ]
    out = expand(sample_rows, groups, header)
    lines = out.strip().splitlines()
    assert len(lines) == 4  # header + 3 files
    # organism copied to every row
    assert all("Escherichia coli" in ln for ln in lines[1:])
    # data files + fractions filled
    assert "cond_F01.raw" in out and "\t1\t" in lines[1]
    # coordinate uniqueness: (source, bio rep, tech rep, fraction) distinct
    coords = set()
    h = lines[0].split("\t")
    idx = {
        c: h.index(c)
        for c in [
            "source name",
            "characteristics[biological replicate]",
            "comment[technical replicate]",
            "comment[fraction identifier]",
        ]
    }
    for ln in lines[1:]:
        cells = ln.split("\t")
        key = tuple(cells[idx[c]] for c in idx)
        assert key not in coords, "duplicate coordinate"
        coords.add(key)


def test_expand_disambiguates_repeated_fraction_via_tech_replicate():
    header = [
        "source name",
        "characteristics[biological replicate]",
        "assay name",
        "comment[data file]",
        "comment[technical replicate]",
        "comment[fraction identifier]",
    ]
    # two files with the SAME parsed fraction -> tech replicate must differ
    files = ["cond_F01_a.raw", "cond_F01_b.raw"]
    groups = {"cond": files}
    out = expand([{"characteristics[biological replicate]": "1"}], groups, header)
    lines = out.strip().splitlines()
    h = lines[0].split("\t")
    tr = [ln.split("\t")[h.index("comment[technical replicate]")] for ln in lines[1:]]
    assert set(tr) == {"1", "2"}  # disambiguated


def test_expand_multiple_sample_groups():
    header = [
        "source name",
        "characteristics[disease]",
        "assay name",
        "comment[data file]",
        "comment[fraction identifier]",
        "comment[technical replicate]",
    ]
    files = ["ctrl_F01.raw", "ctrl_F02.raw", "treated_F01.raw"]
    groups = group_samples(files)
    rows = [
        {"source name": "control", "characteristics[disease]": "normal"},
        {"source name": "treated", "characteristics[disease]": "stress"},
    ]
    out = expand(rows, groups, header)
    assert "control" in out and "treated" in out
    assert "normal" in out and "stress" in out


def test_group_samples_excludes_result_tables():
    from sdrf_agentic_annotator.expand import group_samples, is_raw_data_file

    # real raws + supplementary tables saved with .raw extension
    files = [
        "Ecoli_ctrl_F01.raw",
        "Ecoli_ctrl_F02.raw",
        "TABLE_S7_TAB_All_Peptides_run_1_01.raw",
        "TABLE_S4_TAB_All_Proteins_run_1_01.raw",
        "supplementary_results.raw",
    ]
    g = group_samples(files)
    kept = [f for v in g.values() for f in v]
    assert set(kept) == {"Ecoli_ctrl_F01.raw", "Ecoli_ctrl_F02.raw"}
    assert not is_raw_data_file("TABLE_S7_TAB_All_Peptides_run_1_01.raw")
    assert is_raw_data_file("20130326_Ecoli_F03.raw")


def test_parse_fraction_with_trailing_replicate():
    from sdrf_agentic_annotator.expand import parse_fraction

    assert parse_fraction("x_Frac_19_01.RAW") == 19  # fraction followed by _01
    assert parse_fraction("x_Frac_24_03.RAW") == 24


def test_ensure_unique_coordinates():
    from sdrf_agentic_annotator.expand import ensure_unique_coordinates
    from sdrf_agentic_annotator.validator import structural_check
    import tempfile, os

    # 3 rows with IDENTICAL coordinates -> must be disambiguated
    sdrf = (
        "source name\tcharacteristics[biological replicate]\tcomment[technical replicate]\tcomment[fraction identifier]\tcomment[data file]\n"
        "S1\t1\t1\t1\ta.raw\nS1\t1\t1\t1\tb.raw\nS1\t1\t1\t1\tc.raw"
    )
    out = ensure_unique_coordinates(sdrf)
    trs = [ln.split("\t")[2] for ln in out.splitlines()[1:]]
    assert trs == ["1", "2", "3"]
    p = tempfile.mktemp(suffix=".tsv")
    open(p, "w").write(out)
    assert structural_check(p)[1] == 0  # no collisions
    os.unlink(p)
