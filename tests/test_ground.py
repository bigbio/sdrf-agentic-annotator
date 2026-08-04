from sdrf_agentic_annotator.ground import (
    build_name_index,
    ground_accessions,
)


def _idx():
    labels = {
        "MS:1001910": "LTQ Orbitrap Elite",
        "MS:1001251": "Trypsin",
        "MS:1002038": "label free sample",
        "MS:1000042": "data-dependent acquisition",
        "PRIDE:9999": "trypsin",  # non-MS prefix -> excluded from an MS index
    }
    return build_name_index(labels)


def test_index_is_ms_scoped():
    idx = _idx()
    assert idx["trypsin"] == ("MS:1001251", "Trypsin")  # MS entry kept
    # the PRIDE entry does not override or duplicate the MS one
    assert idx["trypsin"][0].startswith("MS:")


def test_index_omits_ambiguous_terms():
    # two MS accessions share a normalized label -> unsafe to ground -> omitted
    labels = {
        "MS:1000042": "data-dependent acquisition",
        "MS:1003221": "data-dependent acquisition",
    }
    idx = build_name_index(labels)
    assert "data-dependent acquisition" not in idx


def test_grounding_overrides_wrong_accession():
    idx = _idx()
    sdrf = (
        "source name\tassay name\tcomment[instrument]\n"
        "S1\tA1\tNT=LTQ Orbitrap Elite;AC=MS:1002264"  # guessed wrong accession
    )
    out, changes = ground_accessions(sdrf, idx)
    assert "AC=MS:1001910" in out
    assert changes == [
        (
            "comment[instrument]",
            "NT=LTQ Orbitrap Elite;AC=MS:1002264",
            "NT=LTQ Orbitrap Elite;AC=MS:1001910",
        )
    ]


def test_grounding_completes_nt_only():
    idx = _idx()
    sdrf = (
        "source name\tassay name\tcomment[cleavage agent details]\nS1\tA1\tNT=trypsin"
    )
    out, changes = ground_accessions(sdrf, idx)
    assert "NT=Trypsin;AC=MS:1001251" in out
    assert len(changes) == 1


def test_grounding_resolves_plain_term():
    idx = _idx()
    sdrf = (
        "source name\tassay name\tcomment[proteomics data acquisition method]\n"
        "S1\tA1\tdata-dependent acquisition"
    )
    out, _ = ground_accessions(sdrf, idx)
    assert "NT=data-dependent acquisition;AC=MS:1000042" in out


def test_grounding_leaves_unknown_terms_untouched():
    idx = _idx()
    sdrf = (
        "source name\tassay name\tcomment[instrument]\nS1\tA1\tNT=Some Novel Instrument"
    )
    out, changes = ground_accessions(sdrf, idx)
    assert "NT=Some Novel Instrument" in out
    assert changes == []


def test_grounding_skips_not_applicable():
    idx = _idx()
    sdrf = "source name\tassay name\tcomment[label]\nS1\tA1\tnot applicable"
    out, changes = ground_accessions(sdrf, idx)
    assert "not applicable" in out
    assert changes == []


def test_grounding_only_touches_cv_columns():
    idx = _idx()
    # 'trypsin' also appears in a characteristics column -> must NOT be grounded
    sdrf = (
        "source name\tcharacteristics[disease]\tassay name\tcomment[cleavage agent details]\n"
        "S1\ttrypsin\tA1\tNT=trypsin"
    )
    out, changes = ground_accessions(sdrf, idx)
    rows = out.splitlines()[1].split("\t")
    assert rows[1] == "trypsin"  # disease cell untouched
    assert rows[3] == "NT=Trypsin;AC=MS:1001251"  # cleavage grounded
    assert len(changes) == 1


def test_grounding_preserves_row_count_and_header():
    idx = _idx()
    sdrf = (
        "source name\tassay name\tcomment[instrument]\n"
        "S1\tA1\tNT=LTQ Orbitrap Elite\n"
        "S2\tA2\tNT=LTQ Orbitrap Elite\n"
    )
    out, changes = ground_accessions(sdrf, idx)
    lines = out.strip().splitlines()
    assert lines[0] == "source name\tassay name\tcomment[instrument]"
    assert len(lines) == 3  # header + 2 data
    assert len(changes) == 2


def test_strip_removes_wrong_accession_to_nt_only():
    from sdrf_agentic_annotator.ground import strip_mismatched_accessions

    sdrf = (
        "source name\tassay name\tcomment[instrument]\n"
        "S1\tA1\tNT=LTQ Orbitrap Elite;AC=MS:1002264"
    )
    labels = {"MS:1002264": "byonic:deltamod"}  # AC labels something else
    out, stripped = strip_mismatched_accessions(sdrf, labels)
    assert "NT=LTQ Orbitrap Elite" in out and "AC=MS:1002264" not in out
    assert len(stripped) == 1


def test_strip_keeps_correct_accession():
    from sdrf_agentic_annotator.ground import strip_mismatched_accessions

    sdrf = "source name\tassay name\tcomment[label]\nS1\tA1\tNT=label free sample;AC=MS:1002038"
    labels = {"MS:1002038": "label free sample"}
    out, stripped = strip_mismatched_accessions(sdrf, labels)
    assert "AC=MS:1002038" in out
    assert stripped == []


def test_refine_grounds_then_strips():
    from sdrf_agentic_annotator.ground import build_name_index, refine

    idx = build_name_index({"MS:1001251": "Trypsin"})
    labels = {"MS:9999999": "not the instrument", "MS:1001251": "Trypsin"}
    sdrf = (
        "source name\tassay name\tcomment[cleavage agent details]\tcomment[instrument]\n"
        "S1\tA1\tNT=trypsin\tNT=Fake Instr;AC=MS:9999999"
    )
    out, info = refine(sdrf, idx, labels)
    assert "NT=Trypsin;AC=MS:1001251" in out  # grounded
    assert "NT=Fake Instr\t" in out or out.rstrip().endswith(
        "NT=Fake Instr"
    )  # stripped
    assert len(info["grounded"]) == 1 and len(info["stripped"]) == 1


def test_strip_all_columns_catches_nonms_accession():
    from sdrf_agentic_annotator.ground import strip_mismatched_accessions

    # a wrong organism (taxid) accession in a characteristics column
    sdrf = (
        "source name\tcharacteristics[organism]\tassay name\n"
        "S1\tNT=Escherichia coli;AC=NCBITaxon:9606\tA1"
    )
    labels = {"NCBITAXON:9606": "Homo sapiens"}  # 9606 is human, not E. coli
    out, stripped = strip_mismatched_accessions(sdrf, labels, columns=None)
    assert "AC=NCBITaxon:9606" not in out
    assert "NT=Escherichia coli" in out
    assert len(stripped) == 1


def test_refine_strips_nonms_wrong_accession():
    from sdrf_agentic_annotator.ground import build_name_index, refine

    idx = build_name_index({})
    labels = {"NCBITAXON:9606": "Homo sapiens"}
    sdrf = (
        "source name\tcharacteristics[organism]\tassay name\n"
        "S1\tNT=Escherichia coli;AC=NCBITaxon:9606\tA1"
    )
    out, info = refine(sdrf, idx, labels)
    assert "AC=NCBITaxon:9606" not in out
    assert len(info["stripped"]) == 1


def test_alias_resolves_gluc_and_lysc():
    from sdrf_agentic_annotator.ground import build_name_index, ground_accessions

    idx = build_name_index(
        {"MS:1001917": "glutamyl endopeptidase", "MS:1001309": "lys-c"}
    )
    sdrf = (
        "source name\tassay name\tcomment[cleavage agent details]\n"
        "S1\tA1\tNT=Gluc\n"
        "S2\tA2\tNT=LysC"
    )
    out, changes = ground_accessions(sdrf, idx)
    assert "NT=glutamyl endopeptidase;AC=MS:1001917" in out
    assert "NT=lys-c;AC=MS:1001309" in out
    assert len(changes) == 2
