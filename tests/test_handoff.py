from sdrf_agentic_annotator import handoff
from sdrf_agentic_annotator.orchestrator import run_loop

MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "annotate PXD1"}]
SDRF = "source name\tcharacteristics[organism]\nS1\tHomo sapiens\n"


def test_write_request_and_pending(tmp_path):
    handoff.write_request(tmp_path, "PXD000001", messages=MESSAGES, templates=["human"], reason="hard")
    assert handoff.pending(tmp_path) == ["PXD000001"]
    req = (tmp_path / "PXD000001" / "request.json").read_text()
    assert "annotate PXD1" in req and "human" in req


def test_pending_drops_completed(tmp_path):
    handoff.write_request(tmp_path, "PXD000001", messages=MESSAGES)
    (tmp_path / "PXD000001" / "result.sdrf.tsv").write_text(SDRF)
    assert handoff.pending(tmp_path) == []  # has a result now


def test_review_passed_requires_pass_and_matching_hash(tmp_path):
    assert handoff.review_passed({"status": "pass", "artifact_sha256": handoff.sha256(SDRF)}, SDRF) is True
    assert handoff.review_passed({"status": "pass", "artifact_sha256": "deadbeef"}, SDRF) is False  # bound to other text
    assert handoff.review_passed({"status": "fail"}, SDRF) is False
    assert handoff.review_passed({"status": "pass"}, SDRF) is True  # no hash -> accept a pass
    assert handoff.review_passed(None, SDRF) is False


def test_ingest_completed_handoff(tmp_path):
    d = tmp_path / "PXD000001"
    d.mkdir()
    (d / "request.json").write_text("{}")
    assert handoff.ingest(tmp_path, "PXD000001") is None  # no result yet
    (d / "result.sdrf.tsv").write_text(SDRF)
    (d / "review.json").write_text('{"status": "pass", "artifact_sha256": "%s"}' % handoff.sha256(SDRF))
    got = handoff.ingest(tmp_path, "PXD000001")
    assert got == {"accession": "PXD000001", "text": SDRF, "passed": True}


class _FakeLedger:
    def __init__(self, accs):
        self._accs = accs
        self.status = {}

    def reclaim_expired(self, now):
        return 0

    def claim(self, worker_id, n, lease_seconds, now):
        return self._accs[:n]

    def set_status(self, accession, status, **fields):
        self.status[accession] = status


def test_run_loop_escalation_writes_handoff(tmp_path):
    ledger = _FakeLedger(["PXD000009"])
    on_escalate = handoff.make_escalation_writer(tmp_path, build_messages=lambda acc: MESSAGES)
    res = run_loop(
        ledger,
        corpus_dir=str(tmp_path / "corpus"),
        worker_id="w1",
        max_n=5,
        get_sdrf_text=lambda acc: None,  # no deposited SDRF -> escalate
        now=0,
        on_escalate=on_escalate,
    )
    assert res["escalate"] == 1
    assert ledger.status["PXD000009"] == "escalate"
    # the escalation was queued for the sdrf-skills agent
    assert handoff.pending(tmp_path) == ["PXD000009"]
