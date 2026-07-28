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
