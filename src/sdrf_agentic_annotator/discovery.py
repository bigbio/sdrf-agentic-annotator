"""Dataset discovery — find annotation candidates for an organism (or any filter)
minus the ones already annotated elsewhere.

Reusable across campaigns: point it at the local PRIDE projects dump and the
repos that already hold annotations (quantms-datasets, sdrf-annotated-datasets),
and it returns the PXD accessions still needing work. Organism matching is a
simple case-insensitive substring on the project's ``organisms`` names, which
covers strains (e.g. "escherichia coli" matches K-12, BL21, …).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_PXD = re.compile(r"(PXD\d{6,})")


def load_projects(projects_path) -> list:
    """Load the PRIDE projects dump (tolerant of stray control chars)."""
    return json.loads(Path(projects_path).read_text(), strict=False)


def _organism_names(project: dict) -> list[str]:
    out = []
    for o in project.get("organisms") or []:
        name = (
            (o.get("name") or o.get("accession") or "")
            if isinstance(o, dict)
            else str(o)
        )
        if name:
            out.append(str(name).lower())
    return out


def find_by_organism(projects, organism: str) -> list[str]:
    """PXD accessions whose organism list contains ``organism`` (substring, ci)."""
    q = organism.lower()
    accs = []
    for p in projects:
        acc = str(p.get("accession", ""))
        if acc.startswith("PXD") and any(q in n for n in _organism_names(p)):
            accs.append(acc)
    return sorted(set(accs))


def already_annotated(dirs) -> set[str]:
    """PXD accessions already annotated: any PXD-prefixed entry name under the
    given directories (sdrf-annotated-datasets/datasets, /sandbox,
    quantms-datasets/opt-params, …)."""
    seen: set[str] = set()
    for d in dirs:
        base = Path(d)
        if not base.exists():
            continue
        for child in base.iterdir():
            m = _PXD.match(child.name)
            if m:
                seen.add(m.group(1))
    return seen


def candidates(projects_path, organism: str, exclude_dirs) -> dict:
    """End-to-end: organism candidates minus already-annotated. Returns
    {organism, total, annotated_overlap, candidates}."""
    projects = load_projects(projects_path)
    matched = find_by_organism(projects, organism)
    excluded = already_annotated(exclude_dirs)
    cand = sorted(set(matched) - excluded)
    return {
        "organism": organism,
        "total": len(matched),
        "annotated_overlap": len(set(matched) & excluded),
        "candidates": cand,
    }
