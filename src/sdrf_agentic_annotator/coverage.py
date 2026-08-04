"""Template-aware metadata-coverage scoring — the Phase-1b routing gate.

Coverage is measured against the *target template's* columns: given the evidence
gathered for a dataset, what fraction of the template's **required** and
**recommended** columns can we actually fill? The output drives routing —

  * high required-coverage, no hard gaps  -> Qwen (GPU) can annotate reliably
  * unfillable required columns / low score -> escalate to Claude

and it doubles as a worklist: the returned ``hard_gaps`` are exactly the columns
a human/Claude must source. A *hard gap* is an unfillable required column whose
``allow_not_available`` is False (organism, instrument, label, acquisition,
cleavage agent, data file) — these MUST carry a real value. A *soft gap* is an
unfillable column that may legitimately be "not available" (e.g. organism part).

Everything here is a pure function over an ``evidence`` dict so it is testable
without network. ``gather_signals`` maps a cached Bundle + PRIDE project JSON
(+ optional techsdrf output) onto that evidence.
"""

from __future__ import annotations

import re

from .template import Column

# ---- tier weights for the overall score ------------------------------------
TIER_WEIGHT = {"required": 0.70, "recommended": 0.25, "optional": 0.05}
# a required column below this fillability counts as "not available"
FILL_HARD = 0.5
DEFAULT_THRESHOLD = 0.7

_STRUCTURE_TOKEN = re.compile(
    r"(rep|frac|fr|sample|band|gel|f\d|r\d|b\d)", re.IGNORECASE
)
_DELIM = re.compile(r"[_\-.]")


# ============================================================================
# evidence -> per-column fillability
# ============================================================================
# Each rule maps the evidence dict to a 0..1 estimate that the column can be
# populated. Columns with no rule default to 0 (unknown / not expected). The
# rules are intentionally explicit and tunable — they encode *which evidence
# source fills which SDRF column*.


def _has(text: str, *words: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in words)


def _organism(ev) -> float:
    orgs = ev.get("organisms") or []
    if any(len(o) > 1 and str(o[1]).strip() for o in orgs):
        return 1.0
    return 0.5 if orgs else 0.0


def _text_or_deposited(ev, col, *kw) -> float:
    """Fillable if the deposited SDRF already has the column, or protocol/paper
    text mentions any keyword."""
    if col in (ev.get("deposited_columns") or set()):
        return 1.0
    if _has(ev.get("protocol_text", ""), *kw):
        return 0.7
    return 0.3 if ev.get("paper") else 0.0


def _techsdrf_or_protocol(ev, tech_key, *kw) -> float:
    if (ev.get("techsdrf") or {}).get(tech_key):
        return 1.0
    return 0.6 if _has(ev.get("protocol_text", ""), *kw) else 0.0


def _structural(ev) -> float:
    return 1.0 if ev.get("raw_files") else 0.0


FILL_RULES = {
    # --- required: structural (always derivable from the file list) ---
    "source name": _structural,
    "assay name": _structural,
    "comment[data file]": _structural,
    "technology type": lambda ev: 1.0,  # constant for ms-proteomics
    "comment[technical replicate]": lambda ev: 1.0,  # defaults to 1
    # --- required: biological / acquisition (the discriminating ones) ---
    "characteristics[organism]": _organism,
    "characteristics[organism part]": lambda ev: _text_or_deposited(
        ev,
        "characteristics[organism part]",
        "tissue",
        "brain",
        "liver",
        "cell line",
        "plasma",
        "serum",
    ),
    "characteristics[biological replicate]": lambda ev: max(
        0.5,
        ev.get("filenames_structured", 0.0),
        1.0
        if "characteristics[biological replicate]"
        in (ev.get("deposited_columns") or set())
        else 0.0,
    ),
    "comment[fraction identifier]": lambda ev: max(
        0.5,
        ev.get("filenames_structured", 0.0),
        1.0
        if "comment[fraction identifier]" in (ev.get("deposited_columns") or set())
        else 0.0,
    ),
    "comment[proteomics data acquisition method]": lambda ev: (
        1.0
        if (ev.get("techsdrf") or {}).get("acquisition")
        or ev.get("acquisition_confident")
        else 0.6  # Bundle always carries an inferred DDA/DIA value; techsdrf verifies it
    ),
    "comment[instrument]": lambda ev: (
        1.0
        if (ev.get("instruments") or (ev.get("techsdrf") or {}).get("instrument"))
        else 0.0
    ),
    "comment[cleavage agent details]": lambda ev: (
        _techsdrf_or_protocol(
            ev,
            "cleavage_agent",
            "trypsin",
            "lys-c",
            "chymotrypsin",
            "protease",
            "digest",
        )
        or 0.4
    ),  # trypsin is the near-universal default -> partial floor
    "comment[label]": lambda ev: (
        1.0
        if (ev.get("techsdrf") or {}).get("label")
        else 0.7  # 'label free' is the common default
    ),
    # --- recommended ---
    "comment[sdrf version]": lambda ev: 1.0,  # constant
    "characteristics[cell type]": lambda ev: _text_or_deposited(
        ev,
        "characteristics[cell type]",
        "cell",
        "hepatocyte",
        "fibroblast",
        "lymphocyte",
    ),
    "characteristics[disease]": lambda ev: max(
        0.4,  # 'normal' is a defensible default for controls
        _text_or_deposited(
            ev,
            "characteristics[disease]",
            "cancer",
            "tumor",
            "disease",
            "carcinoma",
            "control",
            "healthy",
        ),
    ),
    "comment[dissociation method]": lambda ev: _techsdrf_or_protocol(
        ev, "dissociation", "hcd", "cid", "etd", "collision"
    ),
    "comment[precursor mass tolerance]": lambda ev: _techsdrf_or_protocol(
        ev, "precursor_tolerance", "precursor", "ppm", "tolerance"
    ),
    "comment[fragment mass tolerance]": lambda ev: _techsdrf_or_protocol(
        ev, "fragment_tolerance", "fragment", "da", "tolerance"
    ),
    "comment[modification parameters]": lambda ev: _techsdrf_or_protocol(
        ev,
        "modifications",
        "carbamidomethyl",
        "oxidation",
        "tmt",
        "phospho",
        "acetyl",
        "modification",
    ),
}


def _generic_fill(column: Column, evidence: dict) -> float:
    """Fillability for any column without a specific rule — so coverage stays
    correct for *combined* templates (age, sex, cell line, cellosaurus, …).
    A deposited SDRF that already carries the column fills it; otherwise these
    sample/clinical characteristics live only in the manuscript, so a paper
    gives a weak (below-hard-threshold) signal and its absence gives none."""
    if column.name in (evidence.get("deposited_columns") or set()):
        return 1.0
    return 0.3 if evidence.get("paper") else 0.0


def fillability(column: Column, evidence: dict) -> float:
    rule = FILL_RULES.get(column.name)
    return float(rule(evidence)) if rule else _generic_fill(column, evidence)


# ============================================================================
# aggregation
# ============================================================================


def template_coverage(evidence: dict, templates=None) -> dict:
    """Score `evidence` against a template *combination*. Returns a report with
    per-tier fillable %, hard/soft gap lists, the required-not-available %, an
    overall 0..1 score, the routing tier and the templates used.

    ``templates`` may be a single template name, a list of names to combine, or
    None to auto-select from the evidence (``template.select``).
    """
    from .template import combine, select

    if templates is None:
        names = select(evidence)
    elif isinstance(templates, str):
        names = [templates]
    else:
        names = list(templates)
    cols = combine(names)
    by_tier: dict[str, list[tuple[Column, float]]] = {
        "required": [],
        "recommended": [],
        "optional": [],
    }
    for c in cols:
        by_tier[c.requirement].append((c, fillability(c, evidence)))

    tiers = {}
    for tier, entries in by_tier.items():
        if not entries:
            tiers[tier] = {"fillable_pct": 1.0, "n": 0}
            continue
        fills = [f for (_c, f) in entries]
        tiers[tier] = {
            "fillable_pct": round(sum(fills) / len(fills), 4),
            "n": len(entries),
        }

    # Gaps only come from *required* columns — optional/recommended being
    # unfilled must never block routing. A required, unfillable column is a hard
    # gap when it may NOT be "not available" (na_ok=False), else a soft gap.
    req = by_tier["required"]
    hard_gaps = [c.name for (c, f) in req if f < FILL_HARD and not c.na_ok]
    soft_gaps = [c.name for (c, f) in req if f < FILL_HARD and c.na_ok]
    missing_recommended = [c.name for (c, f) in by_tier["recommended"] if f < FILL_HARD]
    req_na = sum(1 for (_c, f) in req if f < FILL_HARD)
    score = round(
        sum(TIER_WEIGHT[t] * tiers[t]["fillable_pct"] for t in TIER_WEIGHT), 4
    )
    return {
        "score": score,
        "tiers": tiers,
        "required_not_available_pct": round(req_na / len(req), 4) if req else 0.0,
        "hard_gaps": hard_gaps,
        "soft_gaps": soft_gaps,
        "missing_recommended": missing_recommended,
        "templates": names,
    }


def route(report: dict, threshold: float = DEFAULT_THRESHOLD) -> str:
    """'claude' if there is any hard required gap or the score is below the
    (conservative) threshold; otherwise 'qwen'."""
    if report.get("hard_gaps"):
        return "claude"
    return "qwen" if report["score"] >= threshold else "claude"


# ============================================================================
# Bundle/project JSON -> evidence
# ============================================================================


def _filename_structure(bundle) -> float:
    from .fetcher import RAW_EXTS

    raws = [f for f in (getattr(bundle, "files", []) or []) if f.get("ext") in RAW_EXTS]
    if not raws:
        return 0.0
    structured = 0
    for f in raws:
        stem = f.get("name", "").rsplit(".", 1)[0]
        toks = [t for t in _DELIM.split(stem) if t]
        if len(toks) >= 2 or _STRUCTURE_TOKEN.search(stem):
            structured += 1
    return structured / len(raws)


def gather_signals(
    bundle, project_json: dict, techsdrf: dict | None = None, deposited_columns=None
) -> dict:
    """Map a Bundle + cached PRIDE project JSON (+ optional techsdrf output and
    the set of columns present in a deposited SDRF) onto the evidence dict."""
    from .fetcher import RAW_EXTS

    protocol = " ".join(
        str(project_json.get(k, "") or "")
        for k in ("sampleProcessingProtocol", "dataProcessingProtocol")
    )
    has_paper = bool(
        any(
            project_json.get(k)
            for k in ("publications", "references", "labPHeadPublications")
        )
        or any(project_json.get(k) for k in ("doi", "pubmedId", "pmid"))
    )
    raw = any(f.get("ext") in RAW_EXTS for f in (getattr(bundle, "files", []) or []))
    return {
        "raw_files": raw,
        "organisms": list(getattr(bundle, "organisms", []) or []),
        "instruments": list(getattr(bundle, "instruments", []) or []),
        "acquisition_confident": False,  # only techsdrf sets this true
        "protocol_text": protocol,
        "paper": has_paper,
        "filenames_structured": _filename_structure(bundle),
        "deposited_columns": set(deposited_columns or ()),
        "techsdrf": techsdrf or {},
    }


def score_accession(
    cache_dir,
    accession: str,
    templates=None,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict | None:
    """Score one cached accession. Returns None if its cache is absent.

    ``templates`` is a name / list of names to combine, or None to auto-select
    from the evidence. Reads ``{acc}.bundle.json`` + ``{acc}.project.json``
    written by fetch_bundle and returns the template_coverage report plus
    {accession, tier}.
    """
    import json
    from pathlib import Path

    from .models import Bundle

    cache_dir = Path(cache_dir)
    bpath = cache_dir / f"{accession}.bundle.json"
    if not bpath.exists():
        return None
    bundle = Bundle.from_json(bpath.read_text())
    ppath = cache_dir / f"{accession}.project.json"
    project = json.loads(ppath.read_text()) if ppath.exists() else {}
    evidence = gather_signals(bundle, project)
    report = template_coverage(evidence, templates)
    report["accession"] = accession
    report["tier"] = route(report, threshold)
    return report
