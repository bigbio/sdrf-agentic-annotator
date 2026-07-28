from sdrf_harness.run import parse_args, build_get_sdrf_text


def test_parse_args_defaults():
    ns = parse_args(
        ["--accessions-file", "a.txt", "--corpus", "/c", "--db", "l.db", "--worker", "w1"]
    )
    assert ns.accessions_file == "a.txt"
    assert ns.corpus == "/c"
    assert ns.worker == "w1"
    assert ns.max == 25


def test_parse_args_max_override():
    ns = parse_args(
        [
            "--accessions-file",
            "a.txt",
            "--corpus",
            "/c",
            "--db",
            "l.db",
            "--worker",
            "w1",
            "--max",
            "5",
        ]
    )
    assert ns.max == 5


def test_get_sdrf_text_none_when_no_bundle(tmp_path):
    getter = build_get_sdrf_text(tmp_path)  # empty cache dir, no <acc>.bundle.json
    assert getter("PXDMISSING") is None


def test_get_sdrf_text_normalizes(tmp_path, monkeypatch):
    from sdrf_harness import run as runmod
    from sdrf_harness.models import Bundle
    # a bundle whose fetched SDRF lacks technology type + acquisition
    b = Bundle(accession="PXD9", repository="pride", deposited_sdrf="sdrf.tsv",
               deposited_sdrf_url="https://x/sdrf.tsv", acquisition="DIA")
    (tmp_path / "PXD9.bundle.json").write_text(b.to_json())
    monkeypatch.setattr(runmod, "fetch_deposited_sdrf",
                        lambda bundle, ym=None, session=None: "source name\tassay name\tcomment[data file]\ns1\tr\ta.raw\n")
    getter = runmod.build_get_sdrf_text(tmp_path)
    out = getter("PXD9")
    cols = out.splitlines()[0].split("\t")
    assert "technology type" in cols
    assert "comment[proteomics data acquisition method]" in cols
    assert "NT=Data-independent acquisition;AC=PRIDE:0000450" in out
