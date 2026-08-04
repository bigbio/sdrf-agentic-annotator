from __future__ import annotations
import tempfile
from pathlib import Path
from .validator import validate
from .merger import stage_sdrf, commit_batch

def process_ready_sdrf(ledger, accession, sdrf_text, corpus_dir, run_cli=True) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".sdrf.tsv", delete=False) as tf:
        tf.write(sdrf_text); tmp = tf.name
    try:
        verdict = validate(tmp, run_cli=run_cli)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if not verdict.passed:
        ledger.set_status(accession, "escalate", block_reason="; ".join(verdict.errors)[:200])
        return "escalate"
    p = stage_sdrf(corpus_dir, accession, sdrf_text)
    commit_batch(corpus_dir, [p], f"Add {accession} SDRF")
    ledger.set_status(accession, "merged")
    return "merged"

def run_loop(ledger, corpus_dir, worker_id, max_n, get_sdrf_text, now,
             lease_seconds=1800, run_cli=False, on_escalate=None) -> dict:
    """Process one batch. ``on_escalate(accession, reason)`` (optional) is called
    whenever a dataset is escalated — wire it to ``handoff.make_escalation_writer``
    to queue the dataset for the sdrf-skills agent. It is best-effort: a failure
    there never aborts the batch."""
    ledger.reclaim_expired(now)
    claimed = ledger.claim(worker_id, max_n, lease_seconds, now)
    merged = escalate = errors = 0

    def _did_escalate(acc, reason):
        nonlocal escalate
        escalate += 1
        if on_escalate is not None:
            try:
                on_escalate(acc, reason)
            except Exception:
                pass  # hand-off is best-effort; the ledger row is already escalate

    for acc in claimed:
        try:
            text = get_sdrf_text(acc)
            if text is None:
                ledger.set_status(acc, "escalate",
                                  block_reason="no deposited SDRF (needs drafter)")
                _did_escalate(acc, "no deposited SDRF (needs drafter)")
                continue
            if process_ready_sdrf(ledger, acc, text, corpus_dir, run_cli=run_cli) == "merged":
                merged += 1
            else:
                _did_escalate(acc, "deposited SDRF failed validation")
        except Exception:
            # transient failure (e.g. network) — leave the row claimed so its lease
            # expires and reclaim_expired retries it later; don't abort the batch.
            errors += 1
            continue
    return {"claimed": len(claimed), "merged": merged, "escalate": escalate, "errors": errors}
