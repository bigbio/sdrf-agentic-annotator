# tests/test_orchestrator.py
import subprocess
from pathlib import Path
from sdrf_agentic_annotator.ledger import Ledger
from sdrf_agentic_annotator.orchestrator import process_ready_sdrf

GOOD = ("source name\tcharacteristics[organism]\tcharacteristics[biological replicate]\t"
        "comment[fraction identifier]\tcomment[technical replicate]\tcomment[data file]\n"
        "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t1\t1\ta.raw\n"
        "s1\tNT=Homo sapiens;AC=NCBITaxon:9606\t1\t2\t1\tb.raw\n")
COLLIDE = GOOD.replace("1\t2\t1\tb.raw", "1\t1\t1\tb.raw")

def _repo(tmp_path):
    d = tmp_path / "corpus"; (d / "datasets").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
    (d / "README.md").write_text("x")
    subprocess.run(["git", "add", "."], cwd=d, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True, capture_output=True)
    return d

def test_good_sdrf_merges(tmp_path):
    d = _repo(tmp_path)
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD1", "repository": "pride", "annotatability": 0.9}])
    r = process_ready_sdrf(lg, "PXD1", GOOD, d, run_cli=False)
    assert r == "merged"
    assert lg.get("PXD1")["status"] == "merged"
    assert (d / "datasets" / "PXD1" / "PXD1.sdrf.tsv").exists()

def test_collision_sdrf_escalates(tmp_path):
    d = _repo(tmp_path)
    lg = Ledger(tmp_path / "l.db"); lg.init_db()
    lg.add_candidates([{"accession": "PXD2", "repository": "pride", "annotatability": 0.9}])
    r = process_ready_sdrf(lg, "PXD2", COLLIDE, d, run_cli=False)
    assert r == "escalate"
    assert lg.get("PXD2")["status"] == "escalate"
    assert not (d / "datasets" / "PXD2").exists()
