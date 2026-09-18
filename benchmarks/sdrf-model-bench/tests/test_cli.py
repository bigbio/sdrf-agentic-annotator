import tarfile

from sdrf_model_bench.cli import build_parser, pack


def test_parser_has_all_commands():
    p = build_parser()
    for cmd in ("select", "freeze", "run", "score", "report", "pack"):
        assert p.parse_args([cmd]).command == cmd


def test_pack_excludes_outputs(tmp_path):
    root = tmp_path / "bench"
    for rel in ("src/sdrf_model_bench/x.py", "data/manifest.tsv", "outputs/m/r/sdrf.tsv",
                "results/slide.png", "README.md", "models.yaml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x")
    out = pack(root, tmp_path / "pack.tar.gz")
    names = tarfile.open(out).getnames()
    assert any(n.endswith("data/manifest.tsv") for n in names)
    assert not any("/outputs/" in n or "/results/" in n for n in names)
