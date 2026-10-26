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
    └── revised/            only if the first review failed and --revise is true
        ├── <PXD>.sdrf.tsv
        ├── <PXD>.evidence.json
        ├── <PXD>.validation.txt
        ├── <PXD>.revision.md
        ├── <PXD>.review.json
        ├── samples.tsv
        └── technical.tsv
```

| File                           | Content                                                                                                                                                                                                                |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `summary.tsv`                  | One row per PXD: `initial_verdict`, `final_verdict` (`PASS` or `FAIL`) and `revised`.                                                                                                                                  |
| `<PXD>.sdrf.tsv`               | The validated SDRF.                                                                                                                                                                                                    |
| `<PXD>.evidence.json`          | The evidence manifest: a source for each value.                                                                                                                                                                        |
| `<PXD>.validation.txt`         | Each validation command, its output and its exit code. The reviewer receives this file.                                                                                                                                |
| `<PXD>.report.md`              | What the agent annotated, the review status (`REVIEW_PENDING_EXTERNAL`) and the open items.                                                                                                                            |
| `<PXD>.coverage.json`          | The `coverage` block of `sdrf-tools audit-existing --json`: `deposited_runs`, `annotated_runs`, `matched_runs`, `fraction`, `missing` and `invented`. If PRIDE cannot be read, it has `fraction: null` and an `error`. |
| `samples.tsv`, `technical.tsv` | The tables that `sdrf-tools build` turns into the SDRF. The revise agent edits these, not the SDRF.                                                                                                                    |
| `evidence/`                    | The project record from `sdrf-tools fetch` that the evidence manifest cites.                                                                                                                                           |
| `<PXD>.review.json`            | The independent review report, in the schema of the `sdrf-adversarial-review` review contract.                                                                                                                         |
| `revised/<PXD>.revision.md`    | Each review finding, and what the revise agent changed for it or why it did not.                                                                                                                                       |

Use the SDRF in `revised/` when it exists. The pipeline logs one warning that lists the PXDs whose final verdict is not `PASS`.

### Refine mode

With `--refine`, the output differs:

```
<outdir>/
├── refine_summary.tsv
└── <PXD>/
    ├── <PXD>.refine_verdict.json     ← chosen SDRF, verdicts/confidence/coverage for both
    └── <PXD>.sdrf.tsv                ← either the refined SDRF (accepted) or the existing one (kept)
```

| File                        | Content                                                                                                                               |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `refine_summary.tsv`        | One row per PXD: `baseline_verdict`, `refined_verdict`, `chosen` (`refined` or `baseline`), coverage and confidence for each version. |
| `<PXD>.refine_verdict.json` | The full decision: `chosen`, `reason`, and the `baseline`/`refined` `verdict`, `confidence` and `coverage`.                           |
| `<PXD>.sdrf.tsv`            | The chosen SDRF — the refined one if the gate accepted it (`chosen: refined`), otherwise the existing SDRF (`chosen: baseline`).      |

The refined and baseline SDRFs, their evidence manifests, the per-version coverage and the two
review reports are always produced inside the run's work directory; only the chosen outcome is
published. `chosen: baseline` means the existing SDRF was kept because the refined version was
not strictly better.

### Pipeline information

`<outdir>/pipeline_info/` holds the Nextflow execution report, timeline, trace and DAG of each
run. The trace and the report show the run time of each agent task. `software_versions.yml`
records the versions of `sdrf-skills-tools` and `sdrf-pipelines`, the runner image digest, the
agent model and provider, and the Nextflow and pipeline versions.
