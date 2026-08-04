import json

from sdrf_agentic_annotator.batch import main, prepare
from sdrf_agentic_annotator.models import Bundle


def _cache(tmp_path, acc, organisms, instruments, deposited=True, protocol=True):
    b = Bundle(
        accession=acc,
        repository="pride",
        organisms=organisms,
        instruments=instruments,
        files=[
            {"name": "s_rep1_F01.raw", "ext": "raw"},
            {"name": "s_rep2_F01.raw", "ext": "raw"},
        ],
        deposited_sdrf=f"{acc}.sdrf.tsv" if deposited else None,
    )
    (tmp_path / f"{acc}.bundle.json").write_text(b.to_json())
    proj = {}
    if protocol:
        proj = {
            "publications": [{"doi": "1"}],
            "sampleProcessingProtocol": "liver tissue digested with trypsin " * 8,
            "dataProcessingProtocol": "carbamidomethyl oxidation ppm tolerance hcd "
            * 8,
        }
    (tmp_path / f"{acc}.project.json").write_text(json.dumps(proj))


def test_prepare_writes_prompts_and_manifest(tmp_path):
    out = tmp_path / "out"
    _cache(tmp_path, "PXD1", [("Homo sapiens", "9606")], ["Q Exactive"])
    _cache(tmp_path, "PXD2", [], [], deposited=False, protocol=False)  # bare -> claude
    m = prepare(["PXD1", "PXD2", "PXDMISS"], tmp_path, out)
    assert m["counts"]["skipped"] == 1 and "PXDMISS" in m["skipped"]
    # every qwen accession has a prompt file; claude ones do not
    for acc in m["qwen"]:
        assert (out / f"{acc}.prompt.json").exists()
    assert (out / "manifest.json").exists()
    assert (out / "qwen.manifest.txt").exists()


def test_prepare_prompt_content_is_valid_messages(tmp_path):
    out = tmp_path / "out"
    _cache(tmp_path, "PXD1", [("Homo sapiens", "9606")], ["Q Exactive"])
    prepare(["PXD1"], tmp_path, out)
    if (out / "PXD1.prompt.json").exists():
        p = json.loads((out / "PXD1.prompt.json").read_text())
        roles = [m["role"] for m in p["messages"]]
        assert roles == ["system", "user"]
        assert p["n_raw"] == 2


def test_prepare_ranks_datasets_by_score(tmp_path):
    out = tmp_path / "out"
    _cache(tmp_path, "PXD_rich", [("Homo sapiens", "9606")], ["QE"])
    _cache(tmp_path, "PXD_bare", [], [], deposited=False, protocol=False)
    m = prepare(["PXD_bare", "PXD_rich"], tmp_path, out)
    scores = [r["score"] for r in m["datasets"]]
    assert scores == sorted(scores, reverse=True)


def test_batch_cli(tmp_path, capsys):
    out = tmp_path / "out"
    _cache(tmp_path, "PXD1", [("Homo sapiens", "9606")], ["QE"])
    accs = tmp_path / "accs.txt"
    accs.write_text("PXD1\n")
    rc = main(
        ["--accessions-file", str(accs), "--cache", str(tmp_path), "--out", str(out)]
    )
    assert rc == 0
    printed = json.loads(capsys.readouterr().out.strip())
    assert set(printed) == {"qwen", "claude", "skipped"}
