from sdrf_agentic_annotator.validator import full_report

HEAD = ("source name\tcharacteristics[organism]\tcharacteristics[biological replicate]\t"
        "comment[technical replicate]\tcomment[fraction identifier]\t"
        "comment[cleavage agent details]\tcomment[data file]\n")

def _f(tmp_path, body):
    p = tmp_path / "x.sdrf.tsv"; p.write_text(HEAD + body); return p

def test_clean_passes(tmp_path):
    p = _f(tmp_path, "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001251\ta.raw\n"
                     "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t2\tNT=Trypsin;AC=MS:1001251\tb.raw\n")
    r = full_report(p, labels={"MS:1001251": "trypsin"}, run_cli=False)
    assert r.passed and r.collisions == 0 and r.accession_mismatches == []

def test_collision_and_bad_accession_fail(tmp_path):
    p = _f(tmp_path, "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001252\ta.raw\n"
                     "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001252\tb.raw\n")
    r = full_report(p, labels={"MS:1001252": "db source ebi"}, run_cli=False)
    assert not r.passed
    assert r.collisions == 1
    assert any(ac == "MS:1001252" for _, ac, _ in r.accession_mismatches)

def test_no_labels_skips_accession_check(tmp_path):
    p = _f(tmp_path, "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001252\ta.raw\n")
    r = full_report(p, labels=None, run_cli=False)
    assert r.accession_mismatches == [] and r.passed
