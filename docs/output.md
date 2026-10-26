# bigbio/sdrf-agentic-annotator: Output

The pipeline writes all files to `--outdir`.

```
<outdir>/
├── summary.tsv
└── <PXD>/
    ├── <PXD>.sdrf.tsv
    ├── <PXD>.evidence.json
    ├── <PXD>.report.md
    ├── <PXD>.review.json
    └── revised/            only if the first review failed and --revise is true
        ├── <PXD>.sdrf.tsv
        ├── <PXD>.evidence.json
        ├── <PXD>.revision.md
        └── <PXD>.review.json
```

| File | Content |
|---|---|
| `summary.tsv` | One row per PXD: `initial_verdict`, `final_verdict` (`PASS` or `FAIL`) and `revised`. |
| `<PXD>.sdrf.tsv` | The validated SDRF. |
| `<PXD>.evidence.json` | The evidence manifest: a source for each value. |
| `<PXD>.report.md` | What the agent annotated, the validation commands with their exit codes, and the values it could not verify. |
| `<PXD>.review.json` | The independent review report, in the schema of the `sdrf-adversarial-review` review contract. |
| `revised/<PXD>.revision.md` | Each review finding, and what the revise agent changed for it or why it did not. |

Use the SDRF in `revised/` when it exists. The pipeline logs a warning for each PXD whose final verdict is not `PASS`.
