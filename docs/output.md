# bigbio/sdrf-agentic-annotator: Output

The pipeline writes all files to `--outdir`.

```
<outdir>/
├── summary.tsv
└── <PXD>/
    ├── <PXD>.sdrf.tsv
    ├── <PXD>.evidence.json
    ├── <PXD>.validation.txt
    ├── <PXD>.report.md
    ├── <PXD>.review.json
    ├── <PXD>.coverage.json
    ├── samples.tsv
    ├── technical.tsv
    ├── evidence/
    ├── revised/            only if the first review failed and --revise is true
    │   ├── <PXD>.sdrf.tsv
    │   ├── <PXD>.evidence.json
    │   ├── <PXD>.validation.txt
    │   ├── <PXD>.revision.md
    │   ├── <PXD>.coverage.json
    │   ├── <PXD>.review.json
    │   ├── samples.tsv
    │   └── technical.tsv
    └── revised_2/          only with --max_revise 2, if the review in revised/ failed too
        └── ...             the same files as revised/
```

| File | Content |
|---|---|
| `summary.tsv` | One row per PXD: `initial_verdict`, `final_verdict` (`PASS`, `LOW_CONF` or `FAIL`), `revised` (`true` or `false`), the final review's `confidence` (`-1.0` if it gave none) and `coverage` (a fraction, `unverifiable` if PRIDE could not be reached, or `n/a`). |
| `<PXD>.sdrf.tsv` | The validated SDRF. |
| `<PXD>.evidence.json` | The evidence manifest: a source for each value. |
| `<PXD>.validation.txt` | Each validation command, its output and its exit code. The reviewer receives this file. |
| `<PXD>.report.md` | What the agent annotated, the review status (`REVIEW_PENDING_EXTERNAL`) and the open items. |
| `<PXD>.coverage.json` | The `coverage` block of `sdrf-tools audit-existing --json`: `deposited_runs`, `annotated_runs`, `matched_runs`, `fraction`, `missing` and `invented`. If PRIDE cannot be read, it has `fraction: null` and an `error`. |
| `samples.tsv`, `technical.tsv` | The tables that `sdrf-tools build` turns into the SDRF. The revise agent edits these, not the SDRF. |
| `evidence/` | The project record from `sdrf-tools fetch` that the evidence manifest cites. |
| `<PXD>.review.json` | The independent review report, in the schema of the `sdrf-adversarial-review` review contract. |
| `revised/<PXD>.revision.md` | Each review finding, and what the revise agent changed for it or why it did not. |

Use the SDRF in the last revise folder (`revised_2/`, else `revised/`) when it exists. The pipeline logs one warning listing the PXDs whose final verdict is not `PASS`, and one for `LOW_CONF`.

### Refine mode

With `--refine`, the output differs:

```
<outdir>/
├── refine_summary.tsv
└── <PXD>/
    ├── <PXD>.refine_verdict.json     ← chosen SDRF, verdicts/confidence/coverage for both
    ├── <PXD>.sdrf.tsv                ← either the refined SDRF (accepted) or the existing one (kept)
    ├── <PXD>.evidence.json           ← evidence manifest of the chosen SDRF
    ├── <PXD>.review.json             ← review of the chosen SDRF
    └── <PXD>.coverage.json           ← coverage precheck of the chosen SDRF
```

| File | Content |
|---|---|
| `refine_summary.tsv` | One row per PXD: `baseline_verdict`, `refined_verdict` (`n/a` if no refined review was produced), `chosen` (`refined` or `baseline`), coverage (`unverifiable` if PRIDE could not be read) and confidence for each version, and `final_verdict` (the verdict of the chosen SDRF, `LOW_CONF` for a PASS below `--confidence_gate`). |
| `<PXD>.refine_verdict.json` | The full decision: `chosen`, `reason`, and the `baseline`/`refined` `verdict`, `confidence` and `coverage`. |
| `<PXD>.sdrf.tsv` | The chosen SDRF — the refined one if the gate accepted it (`chosen: refined`), otherwise an unchanged copy of the existing SDRF as it was given or fetched (`chosen: baseline`). |
| `<PXD>.evidence.json`, `<PXD>.review.json`, `<PXD>.coverage.json` | The evidence manifest, review report and coverage precheck of the chosen SDRF. For a kept baseline, the evidence manifest was written by the refine agent. |

The version that was not chosen, with its manifest, coverage and review, stays in the run's
work directory. `chosen: baseline` means the existing SDRF was kept because the refined version
was not strictly better.
