from sdrf_agentic_annotator.curate import (
    curate,
    ground_organism,
    normalize_na_wrappers,
)


def test_ground_organism_fixes_hallucination():
    sdrf = (
        "source name\tcharacteristics[organism]\tassay name\n"
        "S1\tHomo sapiens\tA1\n"
        "S2\tHomo sapiens\tA2"
    )
    out, changes = ground_organism(sdrf, [("Escherichia coli", "562")])
    assert "Homo sapiens" not in out
    assert out.count("Escherichia coli") == 2  # both rows fixed
    assert len(changes) == 1  # identical change deduped for reporting


def test_ground_organism_leaves_multi_organism_alone():
    sdrf = "source name\tcharacteristics[organism]\tassay name\nS1\tHomo sapiens\tA1"
    out, changes = ground_organism(
        sdrf, [("Escherichia coli", "562"), ("Homo sapiens", "9606")]
    )
    assert out == sdrf  # cannot disambiguate -> untouched
    assert changes == []


def test_ground_organism_normalizes_nt_format_to_plain():
    sdrf = (
        "source name\tcharacteristics[organism]\tassay name\n"
        "S1\tNT=Escherichia coli;AC=NCBITaxon:562\tA1"
    )
    out, changes = ground_organism(sdrf, [("Escherichia coli", "562")])
    row = out.splitlines()[1].split("\t")
    assert row[1] == "Escherichia coli"  # NT=/AC= stripped to plain
    assert changes == []  # value already matched, only reformatted


def test_ground_organism_consistent_is_noop():
    sdrf = (
        "source name\tcharacteristics[organism]\tassay name\nS1\tEscherichia coli\tA1"
    )
    out, changes = ground_organism(sdrf, [("Escherichia coli", "562")])
    assert changes == []
    assert "Escherichia coli" in out


def test_normalize_na_wrappers():
    sdrf = (
        "source name\tcharacteristics[disease]\tcharacteristics[cell type]\n"
        "S1\tNT=not available\tNT=not applicable"
    )
    out, n = normalize_na_wrappers(sdrf)
    assert "NT=not available" not in out and "NT=not applicable" not in out
    assert "not available" in out and "not applicable" in out
    assert n == 2


def test_curate_combines_both():
    sdrf = (
        "source name\tcharacteristics[organism]\tcharacteristics[disease]\n"
        "S1\tHomo sapiens\tNT=not available"
    )
    out, info = curate(sdrf, [("Escherichia coli", "562")])
    assert "Escherichia coli" in out
    assert "NT=not available" not in out
    assert len(info["organism_fixed"]) == 1 and info["na_normalized"] == 1


def test_normalize_organism_format_strips_wrapper():
    from sdrf_agentic_annotator.curate import normalize_organism_format

    sdrf = (
        "source name\tcharacteristics[organism]\n"
        "S1\tNT=Escherichia coli;AC=NCBITaxon:562\n"
        "S2\tHomo sapiens"
    )
    out, n = normalize_organism_format(sdrf)
    assert "NT=Escherichia coli" not in out and "AC=NCBITaxon" not in out
    assert "Escherichia coli" in out and "Homo sapiens" in out
    assert n == 1  # only the wrapped one changed


def test_normalize_organism_strips_strain_and_expands_abbrev():
    from sdrf_agentic_annotator.curate import normalize_organism_terms

    sdrf = (
        "source name\tcharacteristics[organism]\n"
        "S1\tEscherichia coli (strain K12)\n"
        "S2\tE. coli\n"
        "S3\tEscherichia coli O157:H7 (strain TW14359)"
    )
    out, n = normalize_organism_terms(sdrf)
    for ln in out.splitlines()[1:]:
        assert ln.split("\t")[1] == "Escherichia coli"
    assert n == 3


def test_default_required_cleavage_to_trypsin():
    from sdrf_agentic_annotator.curate import default_required_cv

    sdrf = "source name\tcomment[cleavage agent details]\nS1\tnot available"
    out, n = default_required_cv(sdrf)
    assert "NT=Trypsin;AC=MS:1001251" in out and n == 1


def test_default_label_and_sanitize_values():
    from sdrf_agentic_annotator.curate import default_required_cv, sanitize_values

    out, n = default_required_cv("source name\tcomment[label]\nS1\tnot available")
    assert "label free sample" in out and n == 1
    sdrf = (
        "source name\tcomment[sdrf version]\tcomment[precursor mass tolerance]\tcomment[proteomics data acquisition method]\n"
        "S1\t1.0\t1.0\tunknown method"
    )
    out, n = sanitize_values(sdrf)
    r = out.splitlines()[1].split("\t")
    assert (
        r[1] == "v1.1.0"
        and r[2] == "not available"
        and r[3] == "data-dependent acquisition"
    )


def test_sanitize_ontology_columns():
    from sdrf_agentic_annotator.curate import sanitize_ontology_columns

    valid = {"characteristics[organism part]": {"liver", "cell"}}
    sdrf = (
        "source name\tcharacteristics[organism part]\n"
        "S1\tliver\nS2\tsome invalid tissue xyz\nS3\tnot available"
    )
    out, n = sanitize_ontology_columns(sdrf, valid)
    rows = [ln.split("\t")[1] for ln in out.splitlines()[1:]]
    assert rows == ["liver", "not available", "not available"]
    assert n == 1  # only the invalid one changed


def test_fill_empty_cells():
    from sdrf_agentic_annotator.curate import fill_empty_cells

    sdrf = "source name\tcharacteristics[organism part]\tcomment[label]\nS1\t\tlabel free sample\nS2\tliver"
    out, n = fill_empty_cells(sdrf)
    lines = out.splitlines()
    assert lines[1].split("\t") == ["S1", "not available", "label free sample"]
    assert lines[2].split("\t") == ["S2", "liver", "not available"]  # padded
    assert n == 2


def test_default_integer_columns():
    from sdrf_agentic_annotator.curate import default_integer_columns

    sdrf = (
        "source name\tcharacteristics[biological replicate]\tcomment[fraction identifier]\n"
        "S1\tnot available\t2\nS2\t\tabc"
    )
    out, n = default_integer_columns(sdrf)
    rows = [ln.split("\t") for ln in out.splitlines()[1:]]
    assert rows[0] == ["S1", "1", "2"]  # na->1, valid int kept
    assert rows[1] == ["S2", "1", "1"]  # empty->1, non-int->1
    assert n == 3
