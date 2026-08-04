"""Hand-off bridge to the sdrf-skills agent for escalated (hard) datasets.

The harness runs the bulk / deterministic path itself. Datasets it cannot annotate
confidently — no deposited SDRF, or coverage routes them to the strong ("claude")
tier — are handed to an agent running the sdrf-skills ``/sdrf:annotate`` +
``/sdrf:adversarial-review`` workflows. This module is the file-based protocol
between the two systems; the claude tier is asynchronous, so it is a queue, not a
synchronous ``generate`` call.

One directory per accession under a shared hand-off root::

    <root>/<ACCESSION>/request.json      # written by the harness (this module)
    <root>/<ACCESSION>/result.sdrf.tsv   # written by the agent  (the finished SDRF)
    <root>/<ACCESSION>/review.json       # written by the agent  (adversarial-review receipt,
                                         #   bound to sha256(result) — see sdrf-skills review_gate)

Flow:
  1. On escalation the harness calls :func:`write_request` (wire it via
     :func:`make_escalation_writer` into ``orchestrator.run_loop(on_escalate=…)``).
  2. An agent lists :func:`pending`, annotates each with the sdrf-skills skill, and
     writes ``result.sdrf.tsv`` + ``review.json`` back into the accession's directory.
  3. The harness :func:`ingest` verifies the receipt is a *pass* bound to that exact
     SDRF, then the caller merges it and marks the ledger row ``merged``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

REQUEST = "request.json"
RESULT = "result.sdrf.tsv"
REVIEW = "review.json"

_PASS = {"pass", "passed", "approved", "approve"}


def _dir(root, accession: str) -> Path:
    return Path(root) / accession


def sha256(text: str) -> str:
    """SHA-256 of the SDRF text (same binding the sdrf-skills review gate uses)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_request(
    root,
    accession: str,
    *,
    messages: Sequence[dict],
    templates: Sequence[str] = (),
    evidence: dict | None = None,
    reason: str = "",
) -> Path:
    """Write the escalation request for an agent to pick up; return the request path.

    ``messages`` is the drafting prompt the harness already built from evidence, so
    the agent can start from it (or ignore it and use the skill's own flow).
    """
    d = _dir(root, accession)
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "accession": accession,
        "reason": reason,
        "templates": list(templates),
        "messages": list(messages),
        "evidence": evidence or {},
        "status": "pending",
    }
    path = d / REQUEST
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def pending(root) -> list[str]:
    """Accessions with a request but no result yet — an agent's work list."""
    root = Path(root)
    if not root.exists():
        return []
    return [d.name for d in sorted(root.iterdir()) if (d / REQUEST).exists() and not (d / RESULT).exists()]


def review_passed(review: dict | None, sdrf_text: str) -> bool:
    """True iff the review receipt is a *pass* AND is bound to this exact SDRF.

    Mirrors sdrf-skills' review gate: a receipt is only valid for the artifact it was
    computed on (SHA-256), so any post-review edit invalidates it. If the receipt
    carries no hash we accept a pass verdict; if it carries one it must match.
    """
    if not isinstance(review, dict):
        return False
    status = str(review.get("status") or review.get("verdict") or "").strip().lower()
    if status not in _PASS:
        return False
    bound = review.get("artifact_sha256") or review.get("sha256")
    return bound is None or str(bound) == sha256(sdrf_text)


def read_result(root, accession: str) -> dict | None:
    """Return ``{text, review}`` for a completed hand-off, or ``None`` if not done."""
    result_path = _dir(root, accession) / RESULT
    if not result_path.exists():
        return None
    text = result_path.read_text(encoding="utf-8")
    review: dict = {}
    review_path = _dir(root, accession) / REVIEW
    if review_path.exists():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            review = {}
    return {"text": text, "review": review}


def ingest(root, accession: str) -> dict | None:
    """Read a completed hand-off and whether it is safe to merge.

    Returns ``{accession, text, passed}`` or ``None`` if the agent has not finished.
    """
    res = read_result(root, accession)
    if res is None:
        return None
    return {"accession": accession, "text": res["text"], "passed": review_passed(res["review"], res["text"])}


def make_escalation_writer(
    root,
    build_messages: Callable[[str], Sequence[dict]],
    *,
    templates_of: Callable[[str], Sequence[str]] | None = None,
) -> Callable[[str, str], Path]:
    """Return an ``on_escalate(accession, reason) -> Path`` that writes a hand-off request.

    ``build_messages(accession)`` produces the drafting prompt (e.g. from evidence);
    ``templates_of(accession)`` (optional) records the target templates. Pass the
    returned callable as ``orchestrator.run_loop(on_escalate=…)``.
    """

    def _on_escalate(accession: str, reason: str = "") -> Path:
        messages = build_messages(accession)
        templates = templates_of(accession) if templates_of else ()
        return write_request(root, accession, messages=messages, templates=templates, reason=reason)

    return _on_escalate
