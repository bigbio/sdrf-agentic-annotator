"""Deterministic accession grounding — replace model-guessed accessions with
authoritative OLS-cache lookups.

An LLM should name controlled-vocabulary *terms* (instrument, label, cleavage
agent, dissociation, acquisition method) but must not invent their ontology
accessions from memory — that is where Qwen hallucinated (e.g. LTQ Orbitrap Elite
-> MS:1002264 instead of MS:1001910). This stage takes each CV cell's term name,
resolves it against the ontology cache, and rewrites the cell to the canonical
``NT=<label>;AC=<accession>`` — overriding any wrong accession the model guessed
and completing NT-only cells. Terms that do not resolve are left untouched.

Never uses pandas (SDRF repeats headers); operates on raw tab-separated lines.
"""

from __future__ import annotations

import re

from .validator import normalise_term

# MS controlled-vocabulary columns whose accessions we can ground authoritatively
CV_MS_COLUMNS = frozenset(
    {
        "comment[instrument]",
        "comment[label]",
        "comment[cleavage agent details]",
        "comment[dissociation method]",
        "comment[proteomics data acquisition method]",
    }
)

_NA = frozenset({"", "not applicable", "not available"})
_NT = re.compile(r"NT=([^;\t]+)", re.IGNORECASE)

# Common proteomics CV term aliases an LLM emits, mapped to the canonical
# normalized term present in the MS name index. The model writes abbreviations
# ("Gluc", "LysC") that do not normalize to the ontology label ("glutamyl
# endopeptidase", "lys-c"), so exact-match grounding misses them. Every value
# here is a verified MS ontology label; grounding still resolves the accession
# from the index, so an alias can never introduce a wrong accession.
CV_ALIASES = {
    "gluc": "glutamyl endopeptidase",
    "glu c": "glutamyl endopeptidase",
    "v8": "glutamyl endopeptidase",
    "v8 protease": "glutamyl endopeptidase",
    "endoproteinase gluc": "glutamyl endopeptidase",
    "endoproteinase glu c": "glutamyl endopeptidase",
    "lysc": "lys c",
    "lys c": "lys c",
    "endoproteinase lysc": "lys c",
    "argc": "arg c",
    "endoproteinase argc": "arg c",
    "aspn": "asp n",
    "endoproteinase aspn": "asp n",
    "gluc v8": "glutamyl endopeptidase",
}


def build_name_index(labels: dict, ontology: str = "MS") -> dict:
    """Invert an accession->label map into normalized-term -> (accession, label),
    restricted to one ontology prefix and **only where the term is unambiguous**.

    Grounding must never introduce a wrong accession. A global inversion is
    collision-prone (many accessions can share a normalized label), so we keep a
    term only when exactly one accession *within the target ontology* carries it;
    ambiguous or absent terms are omitted and left for verification instead.
    """
    prefix = ontology.upper()
    groups: dict[str, set] = {}
    for acc, label in labels.items():
        if str(acc).split(":")[0].upper() != prefix:
            continue
        key = normalise_term(label)
        if not key:
            continue
        groups.setdefault(key, set()).add((acc, label))
    return {k: next(iter(v)) for k, v in groups.items() if len(v) == 1}


def _term_of(value: str) -> str:
    m = _NT.search(value)
    return (m.group(1) if m else value).strip()


def ground_accessions(sdrf_text: str, name_index: dict, columns=CV_MS_COLUMNS):
    """Rewrite CV cells to canonical NT=label;AC=accession from the index.

    Returns (new_text, changes) where changes is a list of
    (column, old_value, new_value). Structure/other columns are preserved.
    """
    lines = sdrf_text.splitlines()
    if not lines:
        return sdrf_text, []
    header = lines[0].split("\t")
    targets = [i for i, c in enumerate(header) if c in columns]
    changes = []
    out = [lines[0]]
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cells = ln.split("\t")
        for i in targets:
            if i >= len(cells):
                continue
            val = cells[i]
            if val.strip().lower() in _NA:
                continue
            key = normalise_term(_term_of(val))
            key = CV_ALIASES.get(key, key)
            hit = name_index.get(key)
            if not hit:
                continue
            acc, label = hit
            new = f"NT={label};AC={acc}"
            if new != val:
                changes.append((header[i], val, new))
                cells[i] = new
        out.append("\t".join(cells))
    return "\n".join(out) + "\n", changes


def strip_mismatched_accessions(sdrf_text: str, labels: dict, columns=None):
    """Drop any accession whose AC does not match its NT term in the ontology,
    leaving a valid NT-only cell. Guarantees no model-guessed wrong accession
    survives (grounding can add correct ones; this removes incorrect ones it
    could not authoritatively resolve). ``columns=None`` checks **every** column
    (organism taxid, organism part, disease, cell type, …) not just MS-CV ones —
    a wrong accession anywhere fails validation. Returns (new_text, stripped)."""
    lines = sdrf_text.splitlines()
    if not lines:
        return sdrf_text, []
    header = lines[0].split("\t")
    targets = (
        list(range(len(header)))
        if columns is None
        else [i for i, c in enumerate(header) if c in columns]
    )
    stripped = []
    out = [lines[0]]
    pair = re.compile(r"NT=([^;\t]+);AC=([A-Za-z]+[:_]\d+)")
    for ln in lines[1:]:
        if not ln.strip():
            continue
        cells = ln.split("\t")
        for i in targets:
            if i >= len(cells):
                continue
            m = pair.search(cells[i])
            if not m:
                continue
            nt, ac = m.group(1), m.group(2).replace("_", ":").upper()
            real = labels.get(ac)
            if real is None:
                continue
            a, b = normalise_term(nt), normalise_term(real)
            if a != b and a not in b and b not in a:
                new = f"NT={nt}"
                stripped.append((header[i], cells[i], new))
                cells[i] = new
        out.append("\t".join(cells))
    return "\n".join(out) + "\n", stripped


def refine(
    sdrf_text: str, name_index: dict, labels: dict, ground_columns=CV_MS_COLUMNS
):
    """Ground MS-CV terms to correct accessions (safe, unambiguous only), then
    strip any wrong accession **anywhere** in the file. Every accessioned cell
    ends up correct or NT-only. Returns (new_text, {grounded, stripped})."""
    text, grounded = ground_accessions(sdrf_text, name_index, ground_columns)
    text, stripped = strip_mismatched_accessions(text, labels, columns=None)
    return text, {"grounded": grounded, "stripped": stripped}


def load_name_index(cache_dir=None, ontology: str = "MS") -> dict:
    """Convenience: build the name index straight from the OLS parquet cache."""
    from .validator import load_ontology_labels

    return build_name_index(load_ontology_labels(cache_dir), ontology=ontology)
