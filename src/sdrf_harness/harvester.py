from __future__ import annotations
from .models import Bundle
from .fetcher import is_annotatable


def score_annotatability(bundle: Bundle) -> float:
    ok, _ = is_annotatable(bundle)
    if not ok:
        return 0.0
    s = 0.4
    if bundle.deposited_sdrf:
        s += 0.3
    if len(bundle.organisms) == 1:
        s += 0.2
    if bundle.organisms and bundle.organisms[0][1]:
        s += 0.1
    return round(min(s, 1.0), 3)


def to_candidate_row(bundle: Bundle) -> dict:
    return {"accession": bundle.accession, "repository": bundle.repository,
            "annotatability": score_annotatability(bundle)}
