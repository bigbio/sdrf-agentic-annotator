import json

from sdrf_agentic_annotator.evidence import (
    build_evidence,
    build_manifest,
    main,
    parse_deposited_columns,
    score_dataset,
)
from sdrf_agentic_annotator.models import Bundle


def _human_bundle(acc="PXD1"):
    return Bundle(
        accession=acc,
        repository="pride",
        organisms=[("Homo sapiens", "9606")],
        instruments=["Q Exactive"],
        files=[
            {"name": "s_rep1_F01.raw", "ext": "raw"},
            {"name": "s_rep2_F01.raw", "ext": "raw"},
        ],
        deposited_sdrf=f"{acc}.sdrf.tsv",
    )


def _project():
    return {
        "publications": [{"doi": "10.1/x"}],
        "sampleProcessingProtocol": "liver tissue trypsin digestion " * 8,
        "dataProcessingProtocol": "carbamidomethyl oxidation ppm tolerance hcd " * 8,
    }


def _write_cache(tmp_path, acc="PXD1", deposited=None, techsdrf=None):
    (tmp_path / f"{acc}.bundle.json").write_text(_human_bundle(acc).to_json())
    (tmp_path / f"{acc}.project.json").write_text(json.dumps(_project()))
    if deposited is not None:
        (tmp_path / f"{acc}.deposited.sdrf.tsv").write_text(deposited)
    if techsdrf is not None:
        (tmp_path / f"{acc}.techsdrf.json").write_text(json.dumps(techsdrf))


# --- parse_deposited_columns -----------------------------------------------


def test_parse_deposited_columns_handles_repeated_headers():
    header = (
        "source name\tcharacteristics[organism]\tcomment[data file]\tcomment[data file]"
    )
    cols = parse_deposited_columns(header + "\nX\thomo sapiens\ta.raw\tb.raw")
    assert cols == {"source name", "characteristics[organism]", "comment[data file]"}


def test_parse_deposited_columns_empty():
    assert parse_deposited_columns("") == set()


# --- build_evidence ---------------------------------------------------------


def test_build_evidence_none_when_uncached(tmp_path):
    assert build_evidence("PXDNOPE", tmp_path) is None


def test_build_evidence_merges_deposited_columns(tmp_path):
    dep = "source name\tcharacteristics[age]\tcharacteristics[sex]\n1\t40\tmale"
    _write_cache(tmp_path, deposited=dep)
    ev = build_evidence("PXD1", tmp_path)
    assert "characteristics[age]" in ev["deposited_columns"]
    assert ev["paper"] is True


def test_build_evidence_loads_techsdrf_and_sets_acquisition_confident(tmp_path):
    _write_cache(tmp_path, techsdrf={"instrument": "QE HF", "acquisition": "DIA"})
    ev = build_evidence("PXD1", tmp_path)
    assert ev["techsdrf"]["instrument"] == "QE HF"
    assert ev["acquisition_confident"] is True


def test_deposited_age_sex_removes_human_soft_gaps(tmp_path):
    # a human dataset whose deposited SDRF already has age/sex should no longer
    # list them as gaps -> the deposited table sharpens coverage
    dep = "source name\tcharacteristics[age]\tcharacteristics[sex]\tcharacteristics[disease]\n1\t40\tmale\tnormal"
    _write_cache(tmp_path, deposited=dep)
    rep = score_dataset("PXD1", tmp_path)
    assert "human" in rep["templates"]
    assert "characteristics[age]" not in rep["soft_gaps"]
    assert "characteristics[sex]" not in rep["soft_gaps"]


# --- build_manifest ---------------------------------------------------------


def test_build_manifest_ranks_and_tiers(tmp_path):
    _write_cache(tmp_path, acc="PXD1")  # rich human
    # a bare dataset -> hard gaps -> claude
    Bundle_bare = Bundle("PXD2", "pride")
    (tmp_path / "PXD2.bundle.json").write_text(Bundle_bare.to_json())
    m = build_manifest(["PXD1", "PXD2", "PXDMISS"], tmp_path)
    assert m["counts"]["scored"] == 2
    assert m["counts"]["skipped"] == 1
    assert "PXDMISS" in m["skipped"]
    # PXD2 bare -> claude; PXD1 ranked first (higher score)
    assert m["datasets"][0]["accession"] == "PXD1"
    assert "PXD2" in m["by_tier"]["claude"]


def test_manifest_provider_injection(tmp_path):
    _write_cache(tmp_path, acc="PXD1")
    calls = {}

    def fake_techsdrf(cache_dir, acc):
        calls[acc] = True
        return {"instrument": "Fusion", "label": "TMT10", "acquisition": "DDA"}

    m = build_manifest(["PXD1"], tmp_path, get_techsdrf=fake_techsdrf)
    assert calls == {"PXD1": True}
    assert m["counts"]["scored"] == 1


# --- CLI --------------------------------------------------------------------


def test_cli_writes_manifest(tmp_path, capsys):
    _write_cache(tmp_path, acc="PXD1")
    accs = tmp_path / "accs.txt"
    accs.write_text("PXD1\n")
    out = tmp_path / "manifest.json"
    rc = main(
        ["--accessions-file", str(accs), "--cache", str(tmp_path), "--out", str(out)]
    )
    assert rc == 0
    manifest = json.loads(out.read_text())
    assert manifest["counts"]["scored"] == 1
    printed = json.loads(capsys.readouterr().out.strip())
    assert printed["scored"] == 1
