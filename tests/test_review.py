from sdrf_agentic_annotator.review import review_dir, format_report

HEAD = ("source name\tcharacteristics[organism]\tcharacteristics[biological replicate]\t"
        "comment[technical replicate]\tcomment[fraction identifier]\t"
        "comment[cleavage agent details]\tcomment[data file]\n")

def _ds(root, acc, body):
    d = root / "datasets" / acc; d.mkdir(parents=True)
    (d / f"{acc}.sdrf.tsv").write_text(HEAD + body)

def test_review_dir_separates_pass_and_fail(tmp_path):
    _ds(tmp_path, "PXD1", "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001251\ta.raw\n")
    _ds(tmp_path, "PXD2", "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001252\ta.raw\n"
                          "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001252\tb.raw\n")
    res = review_dir(tmp_path, labels={"MS:1001251": "trypsin", "MS:1001252": "db source ebi"})
    assert res["total"] == 2 and res["passed"] == 1
    failed_accs = [p for p, _ in res["failed"]]
    assert any("PXD2" in p for p in failed_accs)
    assert all("PXD1" not in p for p in failed_accs)

def test_format_report_mentions_counts(tmp_path):
    _ds(tmp_path, "PXD1", "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\tNT=Trypsin;AC=MS:1001251\ta.raw\n")
    txt = format_report(review_dir(tmp_path, labels={"MS:1001251": "trypsin"}))
    assert "1" in txt and "pass" in txt.lower()
