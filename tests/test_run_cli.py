from sdrf_harness.run import parse_args


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
