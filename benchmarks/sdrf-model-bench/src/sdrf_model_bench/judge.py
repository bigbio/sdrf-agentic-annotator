"""Reference-guided LLM judge for what exact matching cannot see. The judge never sees model names."""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter

RUBRIC = """You grade an SDRF-Proteomics annotation against a curated reference for the same dataset.
Ignore column order, letter case and formatting. Score each criterion from 0 to 10:
- factor_fidelity: do the factor value columns capture the same experimental comparison as the reference?
- design_fidelity: does the sample-to-file (and channel) mapping match: samples, biological and
  technical replicates, fractions, labels?
- free_text: are free-text characteristics (treatment, individual, time, sample description)
  faithful to the reference?
Reply with only JSON: {"factor_fidelity": n, "design_fidelity": n, "free_text": n, "rationale": "<= 40 words"}"""
KEYS = ("factor_fidelity", "design_fidelity", "free_text")
MAX_CHARS = 40_000


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return {k: float(d[k]) for k in KEYS}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def judge(generate, truth_tsv: str, pred_tsv: str, n: int = 3) -> dict:
    user = (f"## Reference SDRF\n```tsv\n{truth_tsv[:MAX_CHARS]}\n```\n\n"
            f"## Annotation to grade\n```tsv\n{pred_tsv[:MAX_CHARS]}\n```")
    msgs = [{"role": "system", "content": RUBRIC}, {"role": "user", "content": user}]
    usage: Counter = Counter()
    parsed, raw = [], []
    for _ in range(n):
        c = generate(msgs)
        usage.update(c.usage)
        raw.append(c.text)
        p = _parse(c.text)
        if p:
            parsed.append(p)
    out = {"usage": dict(usage), "raw": raw, "judge": None, **{k: None for k in KEYS}}
    if parsed:
        for k in KEYS:
            out[k] = statistics.median(p[k] for p in parsed)
        out["judge"] = round(10 * sum(out[k] for k in KEYS) / len(KEYS), 2)
    return out
