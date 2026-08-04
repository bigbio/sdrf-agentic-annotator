import subprocess
from sdrf_agentic_annotator.ledger import Ledger
from sdrf_agentic_annotator.orchestrator import run_loop

GOOD = ("source name\tcharacteristics[organism]\tcharacteristics[biological replicate]\t"
        "comment[technical replicate]\tcomment[fraction identifier]\tcomment[data file]\n"
        "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\ta.raw\n")

def _repo(tmp_path):
    d = tmp_path / "corpus"; (d / "datasets").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
    (d / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True, capture_output=True)
    return d

def test_run_loop_merges_deposited_and_escalates_missing(tmp_path):
    d = _repo(tmp_path)
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.9},
                       {"accession": "PXD2", "repository": "pride", "annotatability": 0.8}])
    texts = {"PXD1": GOOD, "PXD2": None}
    res = run_loop(lg, d, "w1", max_n=10, get_sdrf_text=lambda a: texts[a], now=1000.0, run_cli=False)
    assert res == {"claimed": 2, "merged": 1, "escalate": 1, "errors": 0}
    assert lg.get("PXD1")["status"] == "merged"
    assert lg.get("PXD2")["status"] == "escalate"


def test_run_loop_tolerates_fetch_error(tmp_path):
    d = _repo(tmp_path)
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.9},
                       {"accession": "PXDBOOM", "repository": "pride", "annotatability": 0.8}])
    def _get(acc):
        if acc == "PXDBOOM":
            raise RuntimeError("network")
        return GOOD
    res = run_loop(lg, d, "w1", max_n=10, get_sdrf_text=_get, now=1000.0, run_cli=False)
    assert res["merged"] == 1 and res["errors"] == 1        # one merged, one errored, batch not aborted
    assert lg.get("PXD1")["status"] == "merged"
    assert lg.get("PXDBOOM")["status"] == "claimed"          # left claimed for lease reclaim/retry
