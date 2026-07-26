from sdrf_harness.ledger import Ledger

def test_claim_is_exclusive_and_ordered(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([
        {"accession": "PXD1", "repository": "pride", "annotatability": 0.9},
        {"accession": "PXD2", "repository": "pride", "annotatability": 0.5},
        {"accession": "PXD3", "repository": "massive", "annotatability": 0.7},
    ])
    got = lg.claim("w1", n=2, lease_seconds=600, now=1000.0)
    assert got == ["PXD1", "PXD3"]                       # highest annotatability first
    again = lg.claim("w2", n=2, lease_seconds=600, now=1000.0)
    assert again == ["PXD2"]                             # w1's claims are not re-handed
    assert lg.get("PXD1")["status"] == "claimed"
    assert lg.get("PXD1")["worker_id"] == "w1"

def test_add_candidates_ignores_duplicates(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    assert lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.5}]) == 1
    assert lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.9}]) == 0

def test_reclaim_expired_lease(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.5}])
    lg.claim("w1", n=1, lease_seconds=600, now=1000.0)
    assert lg.reclaim_expired(now=1000.0 + 500) == 0     # not yet expired
    assert lg.reclaim_expired(now=1000.0 + 700) == 1     # expired -> back to candidate
    assert lg.get("PXD1")["status"] == "candidate"

def test_set_status_and_counts(tmp_path):
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.5}])
    lg.set_status("PXD1", "blocked", block_reason="peak-list-only")
    assert lg.get("PXD1")["status"] == "blocked"
    assert lg.get("PXD1")["block_reason"] == "peak-list-only"
    assert lg.counts()["blocked"] == 1
