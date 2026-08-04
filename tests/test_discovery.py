import json

from sdrf_agentic_annotator.discovery import (
    already_annotated,
    candidates,
    find_by_organism,
    load_projects,
)


def _projects():
    return [
        {"accession": "PXD000001", "organisms": [{"name": "Escherichia coli K-12"}]},
        {"accession": "PXD000002", "organisms": [{"name": "Homo sapiens"}]},
        {"accession": "PXD000003", "organisms": [{"name": "Escherichia coli BL21"}]},
        {
            "accession": "MSV000004",
            "organisms": [{"name": "Escherichia coli"}],
        },  # not PXD
    ]


def test_find_by_organism_matches_strains_substring():
    accs = find_by_organism(_projects(), "escherichia coli")
    assert accs == ["PXD000001", "PXD000003"]  # both strains, MSV excluded


def test_find_by_organism_case_insensitive():
    assert find_by_organism(_projects(), "HOMO SAPIENS") == ["PXD000002"]


def test_already_annotated_scans_pxd_dirs(tmp_path):
    (tmp_path / "PXD000001").mkdir()
    (tmp_path / "PXD000009-topic").mkdir()
    (tmp_path / "README.md").write_text("x")
    got = already_annotated([tmp_path, tmp_path / "does-not-exist"])
    assert got == {"PXD000001", "PXD000009"}


def test_load_projects_tolerates_control_chars(tmp_path):
    p = tmp_path / "proj.json"
    p.write_text('[{"accession": "PXD1", "title": "a\x01b"}]')  # stray control char
    assert load_projects(p)[0]["accession"] == "PXD1"


def test_candidates_subtracts_annotated(tmp_path):
    pj = tmp_path / "projects.json"
    pj.write_text(json.dumps(_projects()))
    ann = tmp_path / "annotated"
    ann.mkdir()
    (ann / "PXD000001").mkdir()  # already annotated
    out = candidates(pj, "escherichia coli", [ann])
    assert out["total"] == 2
    assert out["annotated_overlap"] == 1
    assert out["candidates"] == ["PXD000003"]
