"""SDRF template specs + generic combination.

A real SDRF is annotated against a *combination* of templates: a technology
template (ms-proteomics / affinity-proteomics / …) plus an organism or
sample-context template (human / vertebrates / invertebrates / plants /
cell-lines) and optionally a disease template (oncology-metadata). Combining
tightens requirements — e.g. ``characteristics[disease]`` is *recommended* in
the shared sample layer but *required* under human / cell-lines / oncology, and
those templates add required columns (age, sex, cell line, cellosaurus …).

Coverage scores against the *combined* column set, so it must:
  * load any template's resolved columns (embedded snapshots — the harness has
    no sdrf-pipelines import dependency; ``refresh_from_registry`` regenerates),
  * ``combine`` several templates: union of columns, **strictest requirement
    wins**, and ``na_ok`` is AND-ed (any template forbidding "not available"
    wins), and
  * ``select`` a sensible default combination from the gathered evidence
    (overridable — the annotating agent may choose a different combination).
"""

from __future__ import annotations

from dataclasses import dataclass

from .template_snapshots import SNAPSHOTS

REQ_RANK = {"optional": 0, "recommended": 1, "required": 2}
_RANK_REQ = {v: k for k, v in REQ_RANK.items()}

# templates by role (for selection); values must exist in SNAPSHOTS
DEFAULT_TECHNOLOGY = "ms-proteomics"
ORGANISM_TEMPLATES = {
    "human": "human",
    "vertebrates": "vertebrates",
    "invertebrates": "invertebrates",
    "plants": "plants",
}


@dataclass(frozen=True)
class Column:
    name: str
    requirement: str  # required | recommended | optional
    na_ok: bool  # allow_not_available


def available_templates() -> list[str]:
    return sorted(SNAPSHOTS)


def load_template(name: str = "ms-proteomics") -> list[Column]:
    """Resolved column spec for a single template, from the embedded snapshot."""
    if name not in SNAPSHOTS:
        raise KeyError(f"no embedded snapshot for template {name!r}")
    return [Column(n, r, na) for (n, r, na) in SNAPSHOTS[name]]


def combine(names) -> list[Column]:
    """Merge several templates into one column spec.

    Union of columns in first-seen order; when a column appears in more than one
    template its requirement is the strictest (required > recommended > optional)
    and its na_ok is AND-ed (False — must carry a real value — wins).
    """
    order: list[str] = []
    req: dict[str, int] = {}
    na: dict[str, bool] = {}
    for name in names:
        for c in load_template(name):
            if c.name not in req:
                order.append(c.name)
                req[c.name] = REQ_RANK[c.requirement]
                na[c.name] = c.na_ok
            else:
                req[c.name] = max(req[c.name], REQ_RANK[c.requirement])
                na[c.name] = na[c.name] and c.na_ok
    return [Column(n, _RANK_REQ[req[n]], na[n]) for n in order]


# --- plant / invertebrate hints for organism-template selection --------------
# taxid-lineage lookups are out of scope pre-GPU; a small name heuristic covers
# the common cases and the caller can always override the selection.
_PLANT_HINTS = (
    "arabidopsis",
    "oryza",
    "triticum",
    "zea mays",
    "solanum",
    "glycine max",
    "hordeum",
    "nicotiana",
    "populus",
    "vitis",
)
_INVERT_HINTS = (
    "drosophila",
    "caenorhabditis",
    "anopheles",
    "aedes",
    "apis mellifera",
    "bombyx",
    "daphnia",
    "schistosoma",
    "plasmodium",
)
_VERTEBRATE_HINTS = (
    "mus musculus",
    "rattus",
    "danio rerio",
    "gallus",
    "sus scrofa",
    "bos taurus",
    "ovis aries",
    "equus caballus",
    "canis",
    "felis catus",
    "macaca",
    "xenopus",
    "oryctolagus",
)


def _organism_template(evidence) -> str | None:
    """The organism template to combine, or None when the organism is not a
    confident match. Unknown organisms (e.g. bacteria, archaea, fungi) get
    technology-only rather than being force-fit to 'vertebrates'."""
    orgs = evidence.get("organisms") or []
    names = " ".join(str(o[0]).lower() for o in orgs if o)
    taxids = {str(o[1]) for o in orgs if len(o) > 1 and o[1]}
    if not orgs:
        return None
    if "9606" in taxids or "homo sapiens" in names:
        return "human"
    if any(h in names for h in _PLANT_HINTS):
        return "plants"
    if any(h in names for h in _INVERT_HINTS):
        return "invertebrates"
    if any(h in names for h in _VERTEBRATE_HINTS):
        return "vertebrates"
    return None  # unknown / microbial -> technology-only (ms-proteomics)


def select(evidence, technology: str | None = None) -> list[str]:
    """Suggest a template combination from the evidence. Overridable.

    tech (default ms-proteomics) + one sample-context template:
      * cell-line evidence          -> cell-lines
      * otherwise organism template -> human / vertebrates / invertebrates / plants
    plus oncology-metadata when the evidence indicates cancer.
    """
    tech = technology or DEFAULT_TECHNOLOGY
    names = [tech]

    text = (evidence.get("protocol_text", "") or "").lower()
    deposited = evidence.get("deposited_columns") or set()
    is_cell_line = (
        evidence.get("cell_line")
        or "characteristics[cell line]" in deposited
        or "cell line" in text
    )
    if is_cell_line:
        names.append("cell-lines")
    else:
        org = _organism_template(evidence)
        if org:
            names.append(org)

    is_cancer = evidence.get("cancer") or any(
        w in text
        for w in ("cancer", "tumor", "tumour", "carcinoma", "oncolog", "neoplas")
    )
    if is_cancer and "oncology-metadata" in SNAPSHOTS:
        names.append("oncology-metadata")
    return names


def refresh_from_registry(names=None) -> dict[str, list[tuple[str, str, bool]]]:
    """Re-resolve templates from sdrf-pipelines (source of truth) to regenerate
    the embedded snapshots. Not called at runtime."""
    from sdrf_pipelines.sdrf.schemas.registry import SchemaRegistry

    reg = SchemaRegistry()
    reg.load_schemas()
    out = {}
    for name in names or SNAPSHOTS:
        schema = reg.get_schema(name)
        if schema is None:
            raise KeyError(name)
        out[name] = [
            (
                c.name,
                c.requirement.value
                if hasattr(c.requirement, "value")
                else str(c.requirement),
                bool(c.allow_not_available),
            )
            for c in schema.columns
        ]
    return out
