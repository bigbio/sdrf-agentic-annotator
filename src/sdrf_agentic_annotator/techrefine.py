"""Empirical refinement stage — wrap `techsdrf refine`.

techsdrf downloads a few raw files, converts to mzML, and reads the spectra to
detect the true instrument (with PSI-MS accession), dissociation method, precursor
/ fragment tolerances, acquisition type (DDA/DIA), mass analyzer, charge range and
isobaric labels/mods — facts an LLM cannot know and should not guess. This stage
overwrites those columns with the empirical values, so it runs *after* the Qwen
draft loop and *before* the deterministic accession `refine` safety net.

Like the parse_sdrf wrapper, the command + env are injectable so it can point at a
techsdrf install in a separate conda env / cluster module without importing it in
process. It degrades gracefully: if techsdrf is absent or errors, the input SDRF
is returned unchanged with ``ok=False`` so the pipeline continues.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

# techsdrf reliably supports Thermo .raw (Bruker .d / SCIEX .wiff need msconvert)
THERMO_EXTS = (".raw", ".raw.gz")
# tokens that vary per run (replicate/fraction/sample counters) — ignored when
# deciding whether two filenames belong to the same instrument/run family
_RUNVAR = frozenset(
    {"rep", "r", "f", "fr", "frac", "fraction", "sample", "s", "run", "tech", "bio"}
)

# columns techsdrf determines empirically from the spectra
TECH_COLUMNS = frozenset(
    {
        "comment[instrument]",
        "comment[proteomics data acquisition method]",
        "comment[dissociation method]",
        "comment[ms2 dissociation method]",
        "comment[ms3 dissociation method]",
        "comment[ms2 mass analyzer]",
        "comment[precursor mass tolerance]",
        "comment[fragment mass tolerance]",
        "comment[collision energy]",
        "comment[isolation window width]",
        "comment[scan window lower limit]",
        "comment[scan window upper limit]",
        "comment[MS min charge]",
        "comment[MS max charge]",
        "comment[modification parameters]",
        "comment[label]",
    }
)


def is_thermo(filename: str) -> bool:
    return filename.lower().endswith(THERMO_EXTS)


def family_signature(filename: str) -> str:
    """A name-family key for a raw file: the set of distinctive alphabetic word
    tokens (length >= 2, not pure run counters), lowercased. Files that differ
    only in replicate/fraction numbers share a family; files whose names carry
    different instrument words (e.g. 'LTQ' vs 'Orbitrap_LTQ') do not."""
    stem = re.sub(r"\.(raw\.gz|raw)$", "", filename.lower())
    words = []
    for tok in re.split(r"[^a-z0-9]+", stem):
        base = re.sub(r"\d+", "", tok)  # strip digits: 'sample1'->'sample', 'f01'->'f'
        if len(base) >= 2 and base not in _RUNVAR:
            words.append(base)
    return "|".join(sorted(set(words))) or stem


def group_raw_families(filenames) -> dict:
    """Group Thermo .raw filenames by name-family. Non-Thermo files are ignored."""
    fams: dict[str, list] = {}
    for f in filenames:
        if is_thermo(f):
            fams.setdefault(family_signature(f), []).append(f)
    return fams


def representative_files(filenames, per_family: int = 1, cap: int = 6) -> list[str]:
    """Pick a representative subset across name-families (Thermo only): up to
    ``per_family`` files from each family, round-robin, capped at ``cap`` total —
    so heterogeneous datasets sample every distinct instrument/run type instead
    of just the first N files (which may all be one family)."""
    fams = group_raw_families(filenames)
    picked: list[str] = []
    ranked = [sorted(v) for _, v in sorted(fams.items())]
    for slot in range(per_family):
        for fam in ranked:
            if slot < len(fam) and len(picked) < cap:
                picked.append(fam[slot])
    return picked


def _diff_cells(old_text: str, new_text: str):
    """Per-cell changes between two SDRFs sharing a header (best-effort)."""
    o_lines = [ln for ln in old_text.splitlines() if ln.strip()]
    n_lines = [ln for ln in new_text.splitlines() if ln.strip()]
    if not o_lines or not n_lines:
        return []
    o_head = o_lines[0].split("\t")
    n_head = n_lines[0].split("\t")
    changes = []
    # map by column name; a column may repeat, so compare positionally where headers match
    for r in range(1, min(len(o_lines), len(n_lines))):
        oc = o_lines[r].split("\t")
        nc = n_lines[r].split("\t")
        for j, col in enumerate(n_head):
            ov = oc[j] if j < len(oc) and j < len(o_head) and o_head[j] == col else None
            nv = nc[j] if j < len(nc) else None
            if ov is not None and nv is not None and ov != nv:
                changes.append((col, ov, nv))
    # dedup preserving order
    seen, out = set(), []
    for c in changes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def techrefine(
    accession: str,
    sdrf_text: str,
    n_files: int = 1,
    skip_ptm: bool = False,
    cmd=("techsdrf", "refine"),
    env: dict | None = None,
    work_dir=None,
    timeout: int = 3600,
) -> dict:
    """Run techsdrf on ``sdrf_text``. Returns
    {ok, text, changes, stdout} — ``text`` is the refined SDRF (or the input
    unchanged when ok is False). ``changes`` is a list of (column, old, new)."""
    tmpdir = tempfile.mkdtemp(prefix="techrefine_")
    inp = Path(tmpdir) / f"{accession}.in.sdrf.tsv"
    outp = Path(tmpdir) / f"{accession}.refined.sdrf.tsv"
    inp.write_text(sdrf_text if sdrf_text.endswith("\n") else sdrf_text + "\n")
    call = [
        *cmd,
        "-p",
        accession,
        "-s",
        str(inp),
        "-o",
        str(outp),
        "-n",
        str(n_files),
    ]
    if skip_ptm:
        call.append("--skip-ptm")
    if work_dir:
        call += ["-w", str(work_dir)]
    try:
        proc = subprocess.run(
            call, capture_output=True, text=True, timeout=timeout, env=env, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {
            "ok": False,
            "text": sdrf_text,
            "changes": [],
            "stdout": f"techsdrf unavailable: {type(e).__name__}",
        }
    if not outp.exists():
        return {
            "ok": False,
            "text": sdrf_text,
            "changes": [],
            "stdout": (proc.stdout + proc.stderr)[-500:],
        }
    refined = outp.read_text()
    return {
        "ok": True,
        "text": refined,
        "changes": _diff_cells(sdrf_text, refined),
        "stdout": (proc.stdout + proc.stderr)[-500:],
    }


def _rows(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return (
        (lines[0].split("\t"), [ln.split("\t") for ln in lines[1:]])
        if lines
        else ([], [])
    )


def _data_file_col(header):
    return (
        header.index("comment[data file]") if "comment[data file]" in header else None
    )


def techrefine_dataset(
    accession: str,
    sdrf_text: str,
    per_family: int = 2,
    max_families: int = 4,
    run=techrefine,
    **run_kw,
) -> dict:
    """Empirically refine an SDRF **per name-family**.

    Groups the Thermo .raw rows into name-families; for each (up to
    ``max_families``) runs techsdrf on that family's representative files and
    merges the empirical TECH_COLUMNS back into *that family's rows only* — so a
    dataset mixing e.g. LTQ and Orbitrap-LTQ runs gets each group refined with
    its own instrument/tolerances instead of one wrong consensus. Non-Thermo rows
    and families beyond the cap are left unchanged. ``run`` is injectable for
    testing. Returns {ok, text, families, analyzed, changes}."""
    header, rows = _rows(sdrf_text)
    dfc = _data_file_col(header)
    if dfc is None or not rows:
        return {
            "ok": False,
            "text": sdrf_text,
            "families": {},
            "analyzed": [],
            "changes": [],
        }

    fam_rows: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        fn = r[dfc] if dfc < len(r) else ""
        if is_thermo(fn):
            fam_rows.setdefault(family_signature(fn), []).append(i)

    # only merge single-instance tech columns: repeated columns (e.g. the split
    # comment[modification parameters]) can't be mapped back by name unambiguously
    # and would be corrupted, so leave them to the PTM/curate stage.
    tech_idx = [
        j for j, c in enumerate(header) if c in TECH_COLUMNS and header.count(c) == 1
    ]
    analyzed, all_changes = [], []
    families_report = {}
    for sig in sorted(fam_rows)[:max_families]:
        idxs = fam_rows[sig]
        reps = representative_files([rows[i][dfc] for i in idxs], per_family=per_family)
        # subset SDRF: header + this family's rows (techsdrf analyses `reps` of them)
        subset = (
            "\n".join(["\t".join(header)] + ["\t".join(rows[i]) for i in idxs]) + "\n"
        )
        res = run(accession, subset, n_files=len(reps) or 1, **run_kw)
        families_report[sig] = {"n_rows": len(idxs), "reps": reps, "ok": res.get("ok")}
        if not res.get("ok"):
            continue
        analyzed += reps
        # map refined values by data-file, then write TECH_COLUMNS into family rows
        r_head, r_rows = _rows(res["text"])
        r_dfc = _data_file_col(r_head)
        by_file = {
            rr[r_dfc]: rr for rr in r_rows if r_dfc is not None and r_dfc < len(rr)
        }
        rmap = {c: k for k, c in enumerate(r_head)}
        for i in idxs:
            rr = by_file.get(rows[i][dfc])
            if not rr:
                continue
            for j in tech_idx:
                col = header[j]
                k = rmap.get(col)
                if (
                    k is not None
                    and k < len(rr)
                    and j < len(rows[i])
                    and rows[i][j] != rr[k]
                ):
                    all_changes.append((col, rows[i][j], rr[k]))
                    rows[i][j] = rr[k]

    merged = "\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n"
    # dedup changes
    seen, changes = set(), []
    for c in all_changes:
        if c not in seen:
            seen.add(c)
            changes.append(c)
    return {
        "ok": bool(analyzed),
        "text": merged,
        "families": families_report,
        "analyzed": analyzed,
        "changes": changes,
    }
