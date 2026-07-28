from sdrf_harness.fetcher import infer_acquisition, parse_pride_project


def test_dia_from_title():
    assert infer_acquisition({"title": "SWATH quantification of X"}) == "DIA"


def test_dia_from_keywords():
    assert infer_acquisition({"keywords": ["data-independent acquisition", "plasma"]}) == "DIA"


def test_default_dda():
    assert infer_acquisition({"title": "Label-free shotgun proteome"}) == "DDA"


def test_bundle_carries_acquisition():
    proj = {"accession": "PXD1", "title": "DIA analysis", "organisms": []}
    b = parse_pride_project(proj, [{"fileName": "a.raw"}])
    assert b.acquisition == "DIA"
