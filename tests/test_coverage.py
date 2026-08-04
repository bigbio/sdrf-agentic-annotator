import json

from sdrf_agentic_annotator.coverage import (
    gather_signals,
    route,
    score_accession,
    template_coverage,
)
from sdrf_agentic_annotator.models import Bundle

# --- fixtures ---------------------------------------------------------------


def _rich_bundle():
    return Bundle(
        accession="PXD000001",
        repository="pride",
        organisms=[("Homo sapiens", "9606")],
        instruments=["Q Exactive"],
        files=[
            {"name": "sample_rep1_F01.raw", "ext": "raw"},
            {"name": "sample_rep1_F02.raw", "ext": "raw"},
            {"name": "sample_rep2_F01.raw", "ext": "raw"},
        ],
        deposited_sdrf="PXD000001.sdrf.tsv",
    )


def _rich_project():
    return {
        "publications": [{"doi": "10.1/x"}],
        "sampleProcessingProtocol": (
            "Liver tissue was lysed, reduced, alkylated and digested with trypsin. " * 8
        ),
        "dataProcessingProtocol": (
            "Searched with carbamidomethyl and oxidation; 10 ppm precursor tolerance, HCD. "
            * 8
        ),
    }


def _rich_evidence():
    return gather_signals(_rich_bundle(), _rich_project())


# --- pure technology template (explicit) ------------------------------------


def test_technology_only_rich_dataset_routes_qwen():
    rep = template_coverage(_rich_evidence(), templates="ms-proteomics")
    assert rep["templates"] == ["ms-proteomics"]
    assert rep["hard_gaps"] == []
    assert rep["tiers"]["required"]["fillable_pct"] >= 0.85
    assert route(rep) == "qwen"


def test_bare_dataset_has_hard_gaps_and_routes_claude():
    ev = gather_signals(Bundle("PXD9", "pride"), {})
    rep = template_coverage(ev, templates="ms-proteomics")
    assert "characteristics[organism]" in rep["hard_gaps"]
    assert "comment[instrument]" in rep["hard_gaps"]
    assert "source name" in rep["hard_gaps"]
    assert rep["required_not_available_pct"] > 0.0
    assert route(rep) == "claude"


def test_missing_instrument_is_a_hard_gap():
    b = _rich_bundle()
    b.instruments = []
    rep = template_coverage(
        gather_signals(b, _rich_project()), templates="ms-proteomics"
    )
    assert "comment[instrument]" in rep["hard_gaps"]
    assert route(rep) == "claude"


def test_organism_part_unfillable_is_soft_not_hard():
    ev = gather_signals(_rich_bundle(), {"publications": [{"doi": "1"}]})
    rep = template_coverage(ev, templates="ms-proteomics")
    assert "characteristics[organism part]" not in rep["hard_gaps"]
    assert "characteristics[organism part]" in rep["soft_gaps"]


def test_techsdrf_fills_instrument():
    b = _rich_bundle()
    b.instruments = []
    ev = gather_signals(b, _rich_project(), techsdrf={"instrument": "Q Exactive HF"})
    rep = template_coverage(ev, templates="ms-proteomics")
    assert "comment[instrument]" not in rep["hard_gaps"]


def test_score_weights_required_most():
    good = template_coverage(_rich_evidence(), templates="ms-proteomics")["score"]
    bare = template_coverage(
        gather_signals(Bundle("P", "pride"), {}), templates="ms-proteomics"
    )["score"]
    assert good > bare > 0.0
    assert good > 0.7


# --- combined templates: the new behaviour ----------------------------------


def test_human_dataset_autoselects_human_and_surfaces_clinical_soft_gaps():
    # human tightens disease->required and adds age/sex (required but na_ok) -> these
    # are SOFT gaps (SDRF-legal as 'not available', paper-fillable), not hard gaps,
    # and they become the worklist the annotator (Qwen/Claude) must hunt in the paper
    rep = template_coverage(_rich_evidence())  # auto-select
    assert rep["templates"] == ["ms-proteomics", "human"]
    for col in (
        "characteristics[age]",
        "characteristics[sex]",
        "characteristics[disease]",
    ):
        assert col in rep["soft_gaps"]
        assert col not in rep["hard_gaps"]
    # combining human raises the required-not-available fraction above 0
    assert rep["required_not_available_pct"] > 0.0


def test_combined_human_has_more_required_gaps_than_technology_only():
    ev = _rich_evidence()
    tech = template_coverage(ev, templates="ms-proteomics")
    human = template_coverage(ev, templates=["ms-proteomics", "human"])
    # combining human tightens/adds required columns (disease, age, sex) -> the
    # required-not-available fraction can only rise
    assert human["required_not_available_pct"] >= tech["required_not_available_pct"]


def test_cell_line_dataset_selects_cell_lines_template():
    b = _rich_bundle()
    ev = gather_signals(b, _rich_project())
    ev["cell_line"] = True
    rep = template_coverage(ev)
    assert "cell-lines" in rep["templates"]
    assert "human" not in rep["templates"]  # cell-lines replaces organism template
    assert "characteristics[cell line]" in rep["hard_gaps"]


def test_cancer_dataset_adds_oncology():
    b = Bundle(
        "P",
        "pride",
        organisms=[("Homo sapiens", "9606")],
        instruments=["QE"],
        files=[{"name": "a_r1.raw", "ext": "raw"}],
    )
    ev = gather_signals(
        b,
        {
            "publications": [{"doi": "1"}],
            "sampleProcessingProtocol": "breast tumor carcinoma tissue",
        },
    )
    rep = template_coverage(ev)
    assert "oncology-metadata" in rep["templates"]


def test_plant_dataset_selects_plants():
    b = Bundle(
        "P",
        "pride",
        organisms=[("Arabidopsis thaliana", "3702")],
        instruments=["QE"],
        files=[{"name": "a_r1.raw", "ext": "raw"}],
    )
    rep = template_coverage(gather_signals(b, {}))
    assert "plants" in rep["templates"]


def test_route_forced_to_claude_by_hard_gap():
    assert route({"score": 0.99, "hard_gaps": ["comment[label]"]}) == "claude"
    assert route({"score": 0.7, "hard_gaps": []}) == "qwen"
    assert route({"score": 0.6999, "hard_gaps": []}) == "claude"


# --- gather_signals ---------------------------------------------------------


def test_gather_signals_detects_paper_and_raw():
    ev = _rich_evidence()
    assert ev["paper"] is True
    assert ev["raw_files"] is True
    assert ev["filenames_structured"] > 0.0


# --- score_accession --------------------------------------------------------


def test_score_accession_missing_cache_returns_none(tmp_path):
    assert score_accession(tmp_path, "PXD404") is None


def test_score_accession_reads_cache_autoselects(tmp_path):
    (tmp_path / "PXD1.bundle.json").write_text(_rich_bundle().to_json())
    (tmp_path / "PXD1.project.json").write_text(json.dumps(_rich_project()))
    out = score_accession(tmp_path, "PXD1")
    assert out["accession"] == "PXD1"
    assert "human" in out["templates"]  # Homo sapiens -> human auto-selected
    assert "score" in out and "tiers" in out


def test_score_accession_explicit_technology_template(tmp_path):
    (tmp_path / "PXD1.bundle.json").write_text(_rich_bundle().to_json())
    (tmp_path / "PXD1.project.json").write_text(json.dumps(_rich_project()))
    out = score_accession(tmp_path, "PXD1", templates="ms-proteomics")
    assert out["templates"] == ["ms-proteomics"]
    assert out["tier"] == "qwen"
