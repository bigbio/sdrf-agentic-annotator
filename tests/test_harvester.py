from sdrf_harness.models import Bundle
from sdrf_harness.harvester import score_annotatability, to_candidate_row


def _b(**kw):
    d = dict(accession="X", repository="pride", organisms=[("Homo sapiens", "9606")],
             files=[{"name": "a.raw", "ext": "raw"}], deposited_sdrf=None)
    d.update(kw); return Bundle(**d)


def test_peaklist_only_scores_zero():
    assert score_annotatability(_b(files=[{"name": "a.mgf", "ext": "mgf"}])) == 0.0


def test_deposited_sdrf_single_organism_scores_highest():
    s = score_annotatability(_b(deposited_sdrf="x.sdrf.tsv"))
    assert s == 1.0


def test_multi_organism_scores_lower_than_single():
    single = score_annotatability(_b())
    multi = score_annotatability(_b(organisms=[("Homo sapiens", "9606"), ("Mus musculus", "10090")]))
    assert multi < single


def test_to_candidate_row():
    row = to_candidate_row(_b())
    assert row["accession"] == "X" and row["repository"] == "pride" and 0 < row["annotatability"] <= 1
