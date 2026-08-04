import dataclasses
from collections import Counter

import pytest

from sdrf_agentic_annotator.template import (
    Column,
    available_templates,
    combine,
    load_template,
    select,
)


def test_ms_proteomics_tier_counts():
    counts = Counter(c.requirement for c in load_template("ms-proteomics"))
    assert counts["required"] == 13
    assert counts["recommended"] == 7
    assert counts["optional"] == 39


def test_available_templates_includes_organism_and_disease():
    avail = available_templates()
    for t in (
        "ms-proteomics",
        "human",
        "vertebrates",
        "plants",
        "cell-lines",
        "oncology-metadata",
    ):
        assert t in avail


def test_unknown_template_raises():
    with pytest.raises(KeyError):
        load_template("does-not-exist")


def test_column_is_frozen():
    c = Column("x", "required", False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.name = "y"  # type: ignore[misc]


# --- combine ---------------------------------------------------------------


def test_combine_unions_columns():
    ms = {c.name for c in load_template("ms-proteomics")}
    human = {c.name for c in load_template("human")}
    combined = {c.name for c in combine(["ms-proteomics", "human"])}
    assert combined == ms | human


def test_combine_strictest_requirement_wins():
    # disease: recommended in ms-proteomics (via sample-metadata), required in human
    combined = {c.name: c for c in combine(["ms-proteomics", "human"])}
    assert combined["characteristics[disease]"].requirement == "required"


def test_combine_na_ok_is_anded():
    # if any template forbids "not available" for a shared column, the combined
    # column forbids it too
    by = {c.name: c for c in combine(["ms-proteomics", "human"])}
    # organism is na_ok=False everywhere -> stays False
    assert by["characteristics[organism]"].na_ok is False


def test_combine_order_is_first_seen():
    cols = combine(["ms-proteomics", "human"])
    names = [c.name for c in cols]
    assert names[0] == "source name"
    assert names.index("technology type") < names.index("characteristics[age]")


# --- select ----------------------------------------------------------------


def test_select_human_from_taxid():
    ev = {"organisms": [("Homo sapiens", "9606")]}
    assert select(ev) == ["ms-proteomics", "human"]


def test_select_plant_from_name():
    ev = {"organisms": [("Arabidopsis thaliana", "3702")]}
    assert "plants" in select(ev)


def test_select_invertebrate_from_name():
    ev = {"organisms": [("Drosophila melanogaster", "7227")]}
    assert "invertebrates" in select(ev)


def test_select_nonhuman_vertebrate_defaults_vertebrates():
    ev = {"organisms": [("Mus musculus", "10090")]}
    assert "vertebrates" in select(ev)


def test_select_cell_line_replaces_organism():
    ev = {"organisms": [("Homo sapiens", "9606")], "cell_line": True}
    names = select(ev)
    assert "cell-lines" in names
    assert "human" not in names


def test_select_cancer_adds_oncology():
    ev = {
        "organisms": [("Homo sapiens", "9606")],
        "protocol_text": "colorectal carcinoma",
    }
    names = select(ev)
    assert "oncology-metadata" in names


def test_select_technology_override():
    ev = {"organisms": [("Homo sapiens", "9606")]}
    names = select(ev, technology="affinity-proteomics")
    assert names[0] == "affinity-proteomics"


def test_select_no_organism_is_technology_only():
    assert select({}) == ["ms-proteomics"]


# --- snapshot drift (skipped when sdrf-pipelines is absent) -----------------


def test_snapshots_match_registry():
    pytest.importorskip("sdrf_pipelines")
    from sdrf_agentic_annotator.template import refresh_from_registry
    from sdrf_agentic_annotator.template_snapshots import SNAPSHOTS

    live = refresh_from_registry(list(SNAPSHOTS))
    for name, rows in SNAPSHOTS.items():
        assert [tuple(r) for r in rows] == live[name], f"snapshot drift in {name}"


def test_select_microbe_is_technology_only():
    # bacteria/archaea/fungi are not vertebrates -> no organism template attached
    ev = {"organisms": [("Escherichia coli", "562")]}
    assert select(ev) == ["ms-proteomics"]


def test_select_mouse_is_vertebrates():
    assert "vertebrates" in select({"organisms": [("Mus musculus", "10090")]})
