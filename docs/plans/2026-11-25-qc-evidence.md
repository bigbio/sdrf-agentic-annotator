# Raw-file QC evidence: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the annotate agent and the reviewer what the raw files show (prideQC), and flag SDRF values the raw files contradict.

**Architecture:** `bin/sdrf_qc.py` reads a dataset's prideQC `annotations.tsv` files and prints Markdown: a summary
for the evidence sheet (`sheet`) and a comparison with an SDRF for the checks (`compare`). SDRF_PREFILL and
SDRF_COVERAGE take the files as an optional `qc: Set<Path>` input (staged as `qc/*/annotations.tsv`) and append
that Markdown to `<pxd>.sheet.md` and `<pxd>.checks.md`. The workflow finds the files of a PXD in
`--qc_index`, a folder of `<PXD>.tsv` files (one annotations.tsv path per line). No prompt changes: the
rules for using the QC are part of the Markdown the agents already read.

**Spec:** `docs/design/2026-11-25-scale-design.md` section F (branch feat/small-extractor).

## Global Constraints

- Observed values (instrument model, dissociation, collision energy) outrank the PRIDE record and the paper;
  inferred values (acquisition method, suggested tolerances) are hints; exploratory evidence (TMT reporter ions,
  mass shifts) is never shown as an SDRF value. Measured mass error is precision, not a search tolerance.
- The QC must never fail a task: a missing or unreadable file gives a section that says so.
- Without `--qc_index` the pipeline behaves exactly as before (no qc input, same task hashes).

## Review Focus

1. A PXD whose runs disagree (two instruments): consensus shows both with counts, no single value claimed.
2. SDRF data files that are not in the QC (archives, renamed files): compared only where names match; the rest counted.
3. `annotations.tsv` cells over 128 KB (mass shifts): parsed without a csv field-size error.
4. Instrument names written differently ("Orbitrap Exploris 480" vs "Exploris 480"; "Q Exactive" vs "Q Exactive HF"): equal only when the same model.
5. A PXD with no QC files: no qc folder, no section, no error.

### Task 1: `bin/sdrf_qc.py` (read, summarise, compare, Markdown) — tests `tests/python/test_sdrf_qc.py`
### Task 2: SDRF_PREFILL and SDRF_COVERAGE take `qc: Set<Path>` and append the sections — nf-test per module
### Task 3: `--qc_index` parameter, `qcFiles(pxd)` helper, wiring in annotate mode and SCORE_SDRF — nf-test of the helper
### Task 4: Codon: split `qc_index.tsv.gz` into `qc_index/by_pxd/<PXD>.tsv`; 20-dataset side run with and without QC
