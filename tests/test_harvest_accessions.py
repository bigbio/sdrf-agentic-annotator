from sdrf_agentic_annotator.ledger import Ledger
from sdrf_agentic_annotator.harvester import harvest_accessions
from sdrf_agentic_annotator.models import Bundle

def _fetch(acc):
    if acc == "BOOM":
        raise RuntimeError("network")
    return Bundle(accession=acc, repository="pride", organisms=[("Homo sapiens", "9606")],
                  files=[{"name": "a.raw", "ext": "raw"}], deposited_sdrf="x.sdrf.tsv")

def test_harvest_adds_candidates_and_skips_failures(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    n = harvest_accessions(lg, ["PXD1", "PXD2", "BOOM"], _fetch)
    assert n == 2
    assert lg.get("PXD1")["status"] == "candidate"
    assert lg.get("BOOM") is None
    assert lg.get("PXD1")["annotatability"] > 0
