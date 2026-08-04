"""Semantic curation — deterministic fixes for quality issues that pass
structural validation but are wrong.

The Qwen drafts validate (correct columns, ontology terms, no collisions) yet can
still be semantically wrong. The dominant case observed on the E. coli batch: the
model wrote ``characteristics[organism] = Homo sapiens`` for datasets PRIDE
declares as *only* Escherichia coli — a hallucinated default. PRIDE's organism
declaration is authoritative, so we ground the organism from it. Also normalizes
stray ``NT=not available`` style wrappers on plain values.

Reusable across organisms; operates on raw tab lines (never pandas).
"""

from __future__ import annotations

import re

_NT_WRAP = re.compile(r"^NT=(not available|not applicable)$", re.IGNORECASE)
_ORG_PLAIN = re.compile(r"^NT=([^;\t]+?)(;AC=[^;\t]+)?$")


def _rows(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], []
    return lines[0].split("\t"), [ln.split("\t") for ln in lines[1:]]


def ground_organism(sdrf_text: str, pride_organisms):
    """Force ``characteristics[organism]`` to PRIDE's declared organism **when
    PRIDE declares exactly one** (the common, safe case) and the SDRF disagrees.

    Multi-organism datasets are left untouched (per-sample organism can't be
    disambiguated deterministically). ``pride_organisms`` is a list of
    (name, taxid). Returns (new_text, changes)."""
    names = [str(o[0]).strip() for o in (pride_organisms or []) if o and o[0]]
    # de-parenthesize e.g. "Escherichia coli (strain K12)" -> keep the full name as declared
    if len(names) != 1:
        return sdrf_text, []
    canonical = names[0]
    header, rows = _rows(sdrf_text)
    if "characteristics[organism]" not in header:
        return sdrf_text, []
    oi = header.index("characteristics[organism]")
    changes = []
    for r in rows:
        if oi < len(r):
            cur = r[oi]
            cur_norm = re.sub(r"NT=|;AC=[^;\t]+", "", cur).strip().lower()
            if cur_norm != canonical.lower():
                changes.append(("characteristics[organism]", cur, canonical))
                r[oi] = canonical
            elif cur != canonical:  # normalize format (strip NT=/AC=) to plain name
                r[oi] = canonical
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, _dedup(changes)


def normalize_organism_format(sdrf_text: str):
    """Make ``characteristics[organism]`` a plain NCBITaxon name (strip any
    ``NT=`` / ``;AC=`` wrapper) on every row — the SDRF convention for organism.
    Applies to single- and multi-organism datasets. Returns (new_text, n_fixed)."""
    header, rows = _rows(sdrf_text)
    if "characteristics[organism]" not in header:
        return sdrf_text, 0
    oi = header.index("characteristics[organism]")
    n = 0
    for r in rows:
        if oi < len(r):
            plain = re.sub(r"NT=|;AC=[^;\t]+", "", r[oi]).strip()
            if plain and plain != r[oi]:
                r[oi] = plain
                n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


_STRAIN = re.compile(
    r"\s*\((?:strain|str\.?|substr\.?)[^)]*\)|\s+o\d+[:_]h\d+", re.IGNORECASE
)
_ORG_ALIASES = {
    "e. coli": "Escherichia coli",
    "e.coli": "Escherichia coli",
    "s. cerevisiae": "Saccharomyces cerevisiae",
    "b. subtilis": "Bacillus subtilis",
    "p. aeruginosa": "Pseudomonas aeruginosa",
    "s. aureus": "Staphylococcus aureus",
    "m. tuberculosis": "Mycobacterium tuberculosis",
}


def normalize_organism_terms(sdrf_text: str):
    """Clean ``characteristics[organism]`` to a base NCBITaxon species term:
    strip strain/substrain qualifiers ("(strain K12)", "O157:H7") and expand
    common abbreviations ("E. coli" -> "Escherichia coli"). Returns (text, n)."""
    header, rows = _rows(sdrf_text)
    if "characteristics[organism]" not in header:
        return sdrf_text, 0
    oi = header.index("characteristics[organism]")
    n = 0
    for r in rows:
        if oi >= len(r):
            continue
        v = r[oi]
        cleaned = _STRAIN.sub("", v).strip()
        cleaned = _ORG_ALIASES.get(cleaned.lower(), cleaned)
        if cleaned and cleaned != v:
            r[oi] = cleaned
            n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


_REQUIRED_DEFAULTS = {
    "comment[cleavage agent details]": "NT=Trypsin;AC=MS:1001251",
    "comment[label]": "NT=label free sample;AC=MS:1002038",
}
_NA_VALS = {"not available", "not applicable", "", "none"}


def default_required_cv(sdrf_text: str):
    """Fill required CV columns the model left as 'not available' with the
    near-universal default (cleavage -> Trypsin, label -> label free sample)."""
    header, rows = _rows(sdrf_text)
    idx = {c: header.index(c) for c in _REQUIRED_DEFAULTS if c in header}
    n = 0
    for r in rows:
        for c, default in _REQUIRED_DEFAULTS.items():
            i = idx.get(c)
            if i is not None and i < len(r) and r[i].strip().lower() in _NA_VALS:
                r[i] = default
                n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


def fix_multi_cleavage(sdrf_text: str):
    """A cleavage cell listing several proteases ("Lys-C, trypsin") isn't a valid
    single CV term. Prefer Trypsin when present (near-universal); otherwise take
    the first named agent. Returns (text, n)."""
    header, rows = _rows(sdrf_text)
    c = "comment[cleavage agent details]"
    if c not in header:
        return sdrf_text, 0
    ci = header.index(c)
    n = 0
    for r in rows:
        if ci >= len(r):
            continue
        v = r[ci]
        if v.startswith("NT=") or v.strip().lower() in _NA_VALS:
            continue
        if re.search(r",| and |;|/", v):
            r[ci] = (
                "NT=Trypsin;AC=MS:1001251"
                if "trypsin" in v.lower()
                else f"NT={re.split(r'[,;/]| and ', v)[0].strip()}"
            )
            n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


_TOL_OK = re.compile(r"\d.*\b(ppm|da|th)\b", re.IGNORECASE)


def sanitize_values(sdrf_text: str):
    """Last-mile value sanitization: sdrf version -> v1.1.0; invalid precursor/
    fragment tolerances -> not available; invalid acquisition method -> DDA."""
    header, rows = _rows(sdrf_text)

    def col(c):
        return header.index(c) if c in header else None

    sv = col("comment[sdrf version]")
    am = col("comment[proteomics data acquisition method]")
    tols = [
        col("comment[precursor mass tolerance]"),
        col("comment[fragment mass tolerance]"),
    ]
    n = 0
    for r in rows:
        if sv is not None and sv < len(r) and r[sv] != "v1.1.0":
            r[sv] = "v1.1.0"
            n += 1
        for t in tols:
            if t is not None and t < len(r):
                v = r[t].strip().lower()
                if v not in _NA_VALS and not _TOL_OK.search(r[t]):
                    r[t] = "not available"
                    n += 1
        if am is not None and am < len(r):
            v = r[am].lower()
            if not any(
                k in v for k in ("dependent", "independent", "dda", "dia", "nt=")
            ):
                r[am] = "data-dependent acquisition"
                n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


_ONTO_COLS = {
    "characteristics[organism part]": ("UBERON", "BTO", "CL", "CLO"),
    "characteristics[cell type]": ("CL", "BTO", "CLO"),
    "characteristics[disease]": ("DOID", "EFO", "MONDO", "PATO", "NCIT", "HP"),
}


def build_valid_terms(labels: dict) -> dict:
    """Per-ontology-column sets of valid normalized term names, from the OLS
    labels. Built once and passed to ``sanitize_ontology_columns`` / ``curate``."""
    from .validator import normalise_term

    sets = {c: set() for c in _ONTO_COLS}
    for acc, lab in labels.items():
        prefix = str(acc).split(":")[0].upper()
        key = normalise_term(lab)
        if not key:
            continue
        for col, prefixes in _ONTO_COLS.items():
            if prefix in prefixes:
                sets[col].add(key)
    return sets


def sanitize_ontology_columns(sdrf_text: str, valid_terms: dict):
    """For ontology-backed characteristics (organism part, cell type, disease),
    replace any value that is not a recognized ontology term with 'not available'
    (they all allow it). Prevents the model's free-text guesses from failing
    validation. Returns (text, n)."""
    from .validator import normalise_term

    header, rows = _rows(sdrf_text)
    targets = [(i, header[i]) for i, c in enumerate(header) if c in valid_terms]
    n = 0
    for r in rows:
        for i, col in targets:
            if i >= len(r):
                continue
            v = r[i].strip()
            if v.lower() in _NA_VALS:
                continue
            if normalise_term(v) not in valid_terms[col]:
                r[i] = "not available"
                n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


# integer columns that require a value (default 1), never 'not available'
_INT_ONE = (
    "characteristics[biological replicate]",
    "comment[technical replicate]",
    "comment[fraction identifier]",
)


def default_integer_columns(sdrf_text: str):
    """Integer columns (biological/technical replicate, fraction identifier) that
    are empty / non-integer / 'not available' default to '1'. Returns (text, n)."""
    header, rows = _rows(sdrf_text)
    idx = [header.index(c) for c in _INT_ONE if c in header]
    n = 0
    for r in rows:
        for i in idx:
            if i < len(r) and not re.fullmatch(
                r"\d+|pooled", r[i].strip(), re.IGNORECASE
            ):
                r[i] = "1"
                n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


def fill_empty_cells(sdrf_text: str):
    """Replace empty cells with 'not available' (SDRF forbids empty cells) and pad
    short rows to the header width. Returns (text, n)."""
    header, rows = _rows(sdrf_text)
    if not header:
        return sdrf_text, 0
    w = len(header)
    n = 0
    for r in rows:
        while len(r) < w:
            r.append("not available")
            n += 1
        for i in range(w):
            if not r[i].strip():
                r[i] = "not available"
                n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


def normalize_na_wrappers(sdrf_text: str):
    """Rewrite ``NT=not available`` / ``NT=not applicable`` cells to the bare
    value (they must be plain, not CV-wrapped). Returns (new_text, n_fixed)."""
    header, rows = _rows(sdrf_text)
    if not header:
        return sdrf_text, 0
    n = 0
    for r in rows:
        for i, c in enumerate(r):
            m = _NT_WRAP.match(c.strip())
            if m:
                r[i] = m.group(1).lower()
                n += 1
    out = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    return out, n


def add_sdrf_template(
    sdrf_text: str, template: str = "ms-proteomics", version: str = "v1.1.0"
):
    """Append a ``comment[sdrf template]`` column (records the template used) if
    the file does not already have one. Returns (new_text, added:bool)."""
    header, rows = _rows(sdrf_text)
    if not header or "comment[sdrf template]" in header:
        return sdrf_text, False
    value = f"NT={template};VV={version}"
    out = ["\t".join([*header, "comment[sdrf template]"])]
    for r in rows:
        out.append("\t".join([*r, value]))
    return "\n".join(out) + "\n", True


def curate(
    sdrf_text: str,
    pride_organisms,
    template: str = "ms-proteomics",
    valid_terms: dict | None = None,
):
    """Apply the deterministic semantic fixes. ``valid_terms`` (from
    ``build_valid_terms(labels)``) enables ontology-column sanitization.
    Returns (new_text, info)."""
    from .ptms import fix_modifications

    text, org = ground_organism(sdrf_text, pride_organisms)
    text, orgfmt = normalize_organism_format(
        text
    )  # plain NCBITaxon name (multi-org too)
    text, orgterm = normalize_organism_terms(
        text
    )  # strip strain qualifiers / expand abbrev
    text, cvmulti = fix_multi_cleavage(text)  # "Lys-C, trypsin" -> Trypsin
    text, cvdef = default_required_cv(text)  # required cleavage/label -> defaults
    text, sanit = sanitize_values(text)  # sdrf version / tolerances / acquisition
    onto = 0
    if valid_terms:
        text, onto = sanitize_ontology_columns(
            text, valid_terms
        )  # organism part/cell/disease
    text, ints = default_integer_columns(text)  # replicate/fraction empties -> 1
    text, empt = fill_empty_cells(
        text
    )  # empty cells -> not available (+pad short rows)
    text, na = normalize_na_wrappers(text)
    text, mods = fix_modifications(text)  # split compact PTM blobs -> UNIMOD columns
    text, tmpl = add_sdrf_template(text, template)
    return text, {
        "organism_fixed": org,
        "organism_reformatted": orgfmt,
        "organism_normalized": orgterm,
        "cv_defaulted": cvdef,
        "cv_multi_fixed": cvmulti,
        "sanitized": sanit,
        "onto_sanitized": onto,
        "empty_filled": empt,
        "int_defaulted": ints,
        "na_normalized": na,
        "mods": mods,
        "template_added": tmpl,
    }


def _dedup(xs):
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
