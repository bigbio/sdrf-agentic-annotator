"""PTM / modification-parameters normalization.

The draft LLM crams several modifications into one ``comment[modification
parameters]`` cell using descriptive names, e.g.::

    NT=Carbamidomethylation of cysteine; NT=Methionine oxidation; NT=protein N-terminal acetylation

The SDRF convention is **one modification per repeated column**, each in the
structured form ``NT=<UNIMOD name>;AC=UNIMOD:<id>;TA=<residue>;MT=<Fixed|Variable>``
(``PP=<position>`` for terminal mods). This module detects the compact blob,
splits it, and maps each modification to its canonical UNIMOD form, restructuring
the mod columns. Unknown modifications are dropped rather than guessed.

Raw tab lines only (never pandas — SDRF repeats the mod header on purpose).
"""

from __future__ import annotations

import re

_MOD_COL = "comment[modification parameters]"

# canonical UNIMOD knowledge for common proteomics modifications
PTM_DB = {
    "carbamidomethyl": {"ac": "UNIMOD:4", "ta": "C", "mt": "Fixed"},
    "oxidation": {"ac": "UNIMOD:35", "ta": "M", "mt": "Variable"},
    "acetyl": {"ac": "UNIMOD:1", "mt": "Variable", "pp": "Protein N-term"},
    "phospho": {"ac": "UNIMOD:21", "ta": "S,T,Y", "mt": "Variable"},
    "deamidated": {"ac": "UNIMOD:7", "ta": "N,Q", "mt": "Variable"},
    "gg": {"ac": "UNIMOD:121", "ta": "K", "mt": "Variable"},  # ubiquitin remnant
    "methyl": {"ac": "UNIMOD:34", "ta": "K,R", "mt": "Variable"},
    "dimethyl": {"ac": "UNIMOD:36", "ta": "K,R", "mt": "Variable"},
    "trimethyl": {"ac": "UNIMOD:37", "ta": "K", "mt": "Variable"},
    "tmt6plex": {"ac": "UNIMOD:737", "ta": "K", "mt": "Fixed", "pp": "Anywhere"},
    "tmt10plex": {"ac": "UNIMOD:737", "ta": "K", "mt": "Fixed", "pp": "Anywhere"},
    "tmt16plex": {"ac": "UNIMOD:2016", "ta": "K", "mt": "Fixed", "pp": "Anywhere"},
    "itraq4plex": {"ac": "UNIMOD:214", "ta": "K", "mt": "Fixed", "pp": "Anywhere"},
    "carbamyl": {"ac": "UNIMOD:5", "ta": "K", "mt": "Variable"},
    "pyro-glu": {"ac": "UNIMOD:28", "ta": "Q", "mt": "Variable", "pp": "N-term"},
}

# descriptive names the model emits -> canonical PTM_DB key
PTM_ALIASES = {
    "carbamidomethylation of cysteine": "carbamidomethyl",
    "carbamidomethylation": "carbamidomethyl",
    "carbamidomethyl (c)": "carbamidomethyl",
    "carboxamidomethylation": "carbamidomethyl",
    "iodoacetamide derivative": "carbamidomethyl",
    "methionine oxidation": "oxidation",
    "oxidation of methionine": "oxidation",
    "oxidation (m)": "oxidation",
    "protein n-terminal acetylation": "acetyl",
    "n-terminal acetylation": "acetyl",
    "n-term acetylation": "acetyl",
    "acetylation": "acetyl",
    "protein acetylation": "acetyl",
    "phosphorylation": "phospho",
    "phosphorylation (sty)": "phospho",
    "deamidation": "deamidated",
    "deamidation (nq)": "deamidated",
    "ubiquitination": "gg",
    "glygly": "gg",
    "methylation": "methyl",
    "dimethylation": "dimethyl",
    "trimethylation": "trimethyl",
    "pyroglutamate": "pyro-glu",
}

_NT = re.compile(r"NT=([^;\t]+)", re.IGNORECASE)
_NA = {"", "not available", "not applicable", "none"}


def _canonical_key(name: str) -> str | None:
    n = re.sub(r"[\s_]+", " ", name.strip().lower())
    if n in PTM_ALIASES:
        return PTM_ALIASES[n]
    if n in PTM_DB:
        return n
    # already a UNIMOD canonical name like "carbamidomethyl"
    base = n.split(" (")[0]
    return base if base in PTM_DB else None


def format_ptm(name: str) -> str | None:
    """Structured SDRF value for a modification name, or None if unknown."""
    key = _canonical_key(name)
    if not key:
        return None
    d = PTM_DB[key]
    display = key[0].upper() + key[1:] if key.islower() else key
    parts = [f"NT={display}", f"AC={d['ac']}"]
    if d.get("ta"):
        parts.append(f"TA={d['ta']}")
    if d.get("mt"):
        parts.append(f"MT={d['mt']}")
    if d.get("pp"):
        parts.append(f"PP={d['pp']}")
    return ";".join(parts)


def _mods_in_cell(cell: str) -> list[str]:
    """Modification names in a cell (handles compact multi-NT blobs)."""
    if cell.strip().lower() in _NA:
        return []
    hits = _NT.findall(cell)
    return [h.strip() for h in hits] if hits else [cell.strip()]


def fix_modifications(sdrf_text: str):
    """Split compact PTM blobs into separate structured mod columns.

    Returns (new_text, {split, mapped, dropped}). Structure of non-mod columns is
    preserved; the ``comment[modification parameters]`` columns are replaced by
    exactly ``max mods per row`` columns (at least one)."""
    lines = [ln for ln in sdrf_text.splitlines() if ln.strip()]
    if not lines:
        return sdrf_text, {"split": 0, "mapped": 0, "dropped": 0}
    header = lines[0].split("\t")
    mod_idx = [i for i, c in enumerate(header) if c == _MOD_COL]
    if not mod_idx:
        return sdrf_text, {"split": 0, "mapped": 0, "dropped": 0}

    rows = [ln.split("\t") for ln in lines[1:]]
    per_row_mods = []
    mapped = dropped = split = 0
    for r in rows:
        names = []
        for i in mod_idx:
            if i < len(r):
                names += _mods_in_cell(r[i])
        if len(names) > 1:
            split += 1
        formatted = []
        for nm in names:
            f = format_ptm(nm)
            if f:
                formatted.append(f)
                mapped += 1
            else:
                dropped += 1
        # de-dup while preserving order
        seen, uniq = set(), []
        for f in formatted:
            if f not in seen:
                seen.add(f)
                uniq.append(f)
        per_row_mods.append(uniq)

    n_cols = max((len(m) for m in per_row_mods), default=0) or 1
    keep = [i for i in range(len(header)) if i not in set(mod_idx)]
    new_header = [header[i] for i in keep] + [_MOD_COL] * n_cols
    out = ["\t".join(new_header)]
    for r, mods in zip(rows, per_row_mods):
        base = [r[i] if i < len(r) else "" for i in keep]
        padded = (mods + ["not available"] * n_cols)[:n_cols]
        out.append("\t".join(base + padded))
    return "\n".join(out) + "\n", {"split": split, "mapped": mapped, "dropped": dropped}
