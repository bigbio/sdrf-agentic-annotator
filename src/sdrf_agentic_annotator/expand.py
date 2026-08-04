"""Sample-level annotation + programmatic row expansion for large datasets.

Datasets with hundreds of raw files overflow the LLM context (prompt lists every
filename and the model must emit a row per file). But a large SDRF is highly
repetitive: the sample-level columns (organism, organism part, disease, cell
type, instrument, cleavage, label, mods…) are constant across the fractions /
replicates of one sample, and only the *technical* columns vary per file
(``comment[data file]``, ``comment[fraction identifier]``, replicates).

So the LLM annotates one row per **sample group** (a handful — fits any context),
and this module expands that to one row per file: copying the sample columns and
filling the technical columns deterministically, with coordinate uniqueness
(source name, biological replicate, technical replicate, fraction identifier)
guaranteed. Raw tab lines only.
"""

from __future__ import annotations

import re

_FRACTION = re.compile(
    r"(?:^|[_\-.])(?:fraction|frac|fr?)[_\-]?(\d{1,3})(?!\d)", re.IGNORECASE
)
# tokens that vary per file within one sample (fraction / replicate / lane)
_FILEVAR = re.compile(
    r"(?:^|[_\-.])(?:fr?|frac|fraction|rep|r|tr?|technical|lane|slice|band|gel|inj)"
    r"[_\-]?\d{1,3}\b",
    re.IGNORECASE,
)
_TECH = ("raw", "wiff", "d", "raw.gz", "wiff.gz")
# names that are supplementary result tables saved with a raw-like extension
# (e.g. "TABLE_S7_TAB_All_Peptides_...raw") — NOT genuine vendor MS raw data
_NOT_RAW = re.compile(
    r"table|all[_\-]?(?:peptides|proteins)|supplementar|readme|results?|report|matrix",
    re.IGNORECASE,
)


def is_raw_data_file(filename: str) -> bool:
    """True for a genuine vendor MS raw file; False for supplementary result
    tables that happen to carry a .raw-like extension."""
    return not _NOT_RAW.search(filename)


def parse_fraction(filename: str) -> int | None:
    """Fraction number from a filename (``…_F03…``, ``frac-2``), else None."""
    m = _FRACTION.search(filename)
    return int(m.group(1)) if m else None


def sample_signature(filename: str) -> str:
    """Sample identity of a raw file: the stem with per-file (fraction/replicate)
    tokens and pure number/date tokens removed. Files that are fractions or
    replicates of the same sample share a signature."""
    stem = re.sub(
        r"\.(raw\.gz|wiff\.gz|raw|wiff|d)$", "", filename, flags=re.IGNORECASE
    )
    stem = _FILEVAR.sub("", stem)
    toks = [t for t in re.split(r"[_\-.\s]+", stem) if t]
    keep = [t for t in toks if not t.isdigit() and not re.fullmatch(r"\d{6,8}", t)]
    return "|".join(keep).lower() or stem.lower()


def group_samples(filenames) -> dict:
    """Group genuine raw filenames by sample signature (order preserved).
    Supplementary result tables (mislabeled with a raw extension) are excluded."""
    groups: dict[str, list] = {}
    for f in filenames:
        if is_raw_data_file(f):
            groups.setdefault(sample_signature(f), []).append(f)
    return groups


def build_expand_messages(bundle, project: dict, templates, groups) -> dict:
    """Compact prompt for a large dataset: ask the LLM for **one SDRF row per
    sample group** (not per file). Sample-level columns only; technical columns
    (data file / fraction / replicates) are filled deterministically by expand().
    Returns {messages, n_groups}."""
    from .prompt import SYSTEM, target_columns

    cols = [
        c
        for c in target_columns(templates)
        if c.name not in ("comment[data file]", "comment[fraction identifier]")
    ]
    colspec = "\n".join(
        f"  {i + 1}. {c.name}  [{c.requirement}]" for i, c in enumerate(cols)
    )
    sig_list = list(groups)
    sample_lines = [
        f"  Sample {i + 1}: {len(groups[s]) + 0} raw files, e.g. {groups[s][0]}"
        for i, s in enumerate(sig_list)
    ]
    acc = getattr(bundle, "accession", "")
    user = "\n".join(
        [
            f"DATASET: {acc}  (LARGE — annotate at the SAMPLE level, one row per sample)",
            f"TITLE: {project.get('title', '')}",
            f"ORGANISM(S): {getattr(bundle, 'organisms', [])}",
            f"INSTRUMENT(S): {getattr(bundle, 'instruments', [])}",
            "",
            "SAMPLE PROCESSING PROTOCOL:",
            str(project.get("sampleProcessingProtocol", "") or ""),
            "",
            "DATA PROCESSING PROTOCOL:",
            str(project.get("dataProcessingProtocol", "") or ""),
            "",
            (
                f"SAMPLES ({len(sig_list)}) — each is a group of related raw files "
                "(fractions/replicates of one sample). Produce EXACTLY one row per "
                "sample, in order:"
            ),
            *sample_lines,
            "",
            (
                f"SDRF COLUMNS (templates: {', '.join(templates)}) — sample-level, in "
                "order (omit data file / fraction; those are added automatically):"
            ),
            colspec,
            "",
            f"Produce the SDRF now: header row + exactly {len(sig_list)} sample rows.",
        ]
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "n_groups": len(sig_list),
    }


def ensure_unique_coordinates(sdrf_text: str) -> str:
    """Guarantee (source name, biological replicate, technical replicate, fraction
    identifier) is unique on every row by assigning the technical replicate as a
    running count within each (source, bio replicate, fraction) group. Bulletproof
    against duplicate source names or unparsed fractions upstream."""
    lines = [ln for ln in sdrf_text.splitlines() if ln.strip()]
    if not lines:
        return sdrf_text
    header = lines[0].split("\t")
    need = [
        "source name",
        "characteristics[biological replicate]",
        "comment[technical replicate]",
        "comment[fraction identifier]",
    ]
    if not all(c in header for c in need):
        return sdrf_text
    si, bi, ti, fi = (header.index(c) for c in need)
    seen: dict[tuple, int] = {}
    out = [lines[0]]
    for ln in lines[1:]:
        r = ln.split("\t")
        if max(si, bi, ti, fi) < len(r):
            key = (r[si], r[bi], r[fi])
            seen[key] = seen.get(key, 0) + 1
            r[ti] = str(seen[key])
        out.append("\t".join(r))
    return "\n".join(out) + "\n"


def expand(sample_rows, groups, columns) -> str:
    """Expand annotated sample rows to one row per file.

    ``sample_rows``: list of dicts (column -> value), one per sample group, in the
    same order as ``groups`` (a dict sig -> [filenames]). ``columns``: the ordered
    SDRF header. Returns the full SDRF text with unique coordinates."""
    header = list(columns)
    out = ["\t".join(header)]
    sig_list = list(groups)
    assay = 0
    for gi, sig in enumerate(sig_list):
        sample = sample_rows[gi] if gi < len(sample_rows) else {}
        files = groups[sig]
        # technical replicate disambiguates files that share a fraction within a sample
        frac_seen: dict[int, int] = {}
        for fn in files:
            assay += 1
            frac = parse_fraction(fn) or 1
            frac_seen[frac] = frac_seen.get(frac, 0) + 1
            row = {c: sample.get(c, "not available") for c in header}
            row["source name"] = sample.get("source name") or f"sample {gi + 1}"
            row["assay name"] = f"run {assay}"
            if "comment[data file]" in row:
                row["comment[data file]"] = fn
            if "comment[fraction identifier]" in row:
                row["comment[fraction identifier]"] = str(frac)
            if "comment[technical replicate]" in row:
                row["comment[technical replicate]"] = str(frac_seen[frac])
            if "technology type" in row and not sample.get("technology type"):
                row["technology type"] = "proteomic profiling by mass spectrometry"
            out.append("\t".join(row.get(c, "not available") for c in header))
    return "\n".join(out) + "\n"
