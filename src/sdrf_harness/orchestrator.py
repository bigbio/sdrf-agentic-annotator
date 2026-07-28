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
             lease_seconds=1800, run_cli=False) -> dict:
    ledger.reclaim_expired(now)
    claimed = ledger.claim(worker_id, max_n, lease_seconds, now)
    merged = escalate = 0
    for acc in claimed:
        text = get_sdrf_text(acc)
        if text is None:
            ledger.set_status(acc, "escalate", block_reason="no deposited SDRF (needs drafter)")
            escalate += 1
            continue
        if process_ready_sdrf(ledger, acc, text, corpus_dir, run_cli=run_cli) == "merged":
            merged += 1
        else:
            escalate += 1
    return {"claimed": len(claimed), "merged": merged, "escalate": escalate}
