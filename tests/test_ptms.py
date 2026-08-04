from sdrf_agentic_annotator.ptms import fix_modifications, format_ptm


def test_format_ptm_canonical_structure():
    assert (
        format_ptm("Carbamidomethylation of cysteine")
        == "NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed"
    )
    assert (
        format_ptm("Methionine oxidation")
        == "NT=Oxidation;AC=UNIMOD:35;TA=M;MT=Variable"
    )
    assert (
        format_ptm("protein N-terminal acetylation")
        == "NT=Acetyl;AC=UNIMOD:1;MT=Variable;PP=Protein N-term"
    )


def test_format_ptm_unknown_returns_none():
    assert format_ptm("some novel modification xyz") is None


def test_fix_compact_blob_splits_into_columns():
    # exactly the PR #51 error pattern
    sdrf = (
        "source name\tcomment[modification parameters]\n"
        "S1\tNT=Carbamidomethylation of cysteine; NT=Methionine oxidation; NT=protein N-terminal acetylation\n"
        "S2\tNT=Carbamidomethylation of cysteine; NT=Methionine oxidation; NT=protein N-terminal acetylation"
    )
    out, info = fix_modifications(sdrf)
    header = out.splitlines()[0].split("\t")
    assert header.count("comment[modification parameters]") == 3  # split into 3 columns
    row = out.splitlines()[1].split("\t")
    assert "NT=Carbamidomethyl;AC=UNIMOD:4;TA=C;MT=Fixed" in row
    assert "NT=Oxidation;AC=UNIMOD:35;TA=M;MT=Variable" in row
    assert "NT=Acetyl;AC=UNIMOD:1;MT=Variable;PP=Protein N-term" in row
    assert info["split"] == 2 and info["mapped"] == 6


def test_fix_pads_rows_with_fewer_mods():
    sdrf = (
        "source name\tcomment[modification parameters]\n"
        "S1\tNT=Carbamidomethyl; NT=Oxidation\n"
        "S2\tNT=Carbamidomethyl"
    )
    out, _ = fix_modifications(sdrf)
    assert (
        out.splitlines()[0].split("\t").count("comment[modification parameters]") == 2
    )
    r2 = out.splitlines()[2].split("\t")
    assert r2[-1] == "not available"  # padded


def test_fix_drops_unknown_mods():
    sdrf = (
        "source name\tcomment[modification parameters]\n"
        "S1\tNT=Oxidation; NT=totally unknown mod"
    )
    out, info = fix_modifications(sdrf)
    assert info["dropped"] == 1 and info["mapped"] == 1
    assert "totally unknown" not in out


def test_fix_noop_when_no_mod_column():
    sdrf = "source name\tcomment[instrument]\nS1\tNT=x"
    out, info = fix_modifications(sdrf)
    assert out == sdrf and info["mapped"] == 0


def test_fix_preserves_other_columns():
    sdrf = (
        "source name\tcharacteristics[organism]\tcomment[modification parameters]\tcomment[label]\n"
        "S1\tEscherichia coli\tNT=Oxidation\tlabel free sample"
    )
    out, _ = fix_modifications(sdrf)
    r = out.splitlines()[1].split("\t")
    assert "Escherichia coli" in r and "label free sample" in r
