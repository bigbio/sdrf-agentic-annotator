# jonasscheid/nf-agent-sdrf

[![CI](https://github.com/jonasscheid/nf-agent-sdrf/actions/workflows/ci.yml/badge.svg)](https://github.com/jonasscheid/nf-agent-sdrf/actions/workflows/ci.yml)
[![Nextflow](https://img.shields.io/badge/nextflow-%E2%89%A526.10.3-23aa62.svg)](https://www.nextflow.io/)

## Introduction

**jonasscheid/nf-agent-sdrf** annotates PRIDE datasets with [SDRF](https://github.com/bigbio/proteomics-sample-metadata). It runs the [bigbio/sdrf-skills](https://github.com/bigbio/sdrf-skills) workflow in Nextflow `agent` tasks.

```
PXD ──► SDRF_ANNOTATE ──► SDRF_REVIEW ──► PASS ──────────────────────────────────► <outdir>/<PXD>/
                                     └──► FAIL ──► SDRF_REVISE ──► SDRF_REVIEW ──► <outdir>/<PXD>/revised/
```

1. `SDRF_ANNOTATE` creates and validates the SDRF and an evidence manifest. It uses the skill `sdrf-annotate`.
2. `SDRF_REVIEW` reviews the SDRF in a fresh context. It uses the skill `sdrf-adversarial-review`.
3. If the review fails, `SDRF_REVISE` fixes the findings once, and `SDRF_REVIEW` reviews the revised SDRF again. Use `--revise false` to skip this step.
4. `summary.tsv` lists the initial and final verdict of each PXD.

> [!WARNING]
> Nextflow agents are a preview feature. The syntax and behavior can change in future Nextflow releases.

## Usage

1. Make a samplesheet with one PXD accession per row:

   ```csv
   pxd
   PXD074155
   ```

2. Store the API key of your LLM provider as the Nextflow secret `LLM_KEY`:

   ```bash
   nextflow secrets set LLM_KEY <your-api-key>
   ```

3. Run the pipeline:

   ```bash
   nextflow run jonasscheid/nf-agent-sdrf -profile docker --input samplesheet.csv --outdir <OUTDIR>
   ```

To test the pipeline with one PXD, use `-profile test,docker`.

See [docs/usage.md](docs/usage.md) for all options and [docs/output.md](docs/output.md) for the output files.

## Credits

jonasscheid/nf-agent-sdrf was written by Jonas Scheid. The annotation and review logic comes from [bigbio/sdrf-skills](https://github.com/bigbio/sdrf-skills). The skills in `modules/local/*/skills/` are copies of bigbio/sdrf-skills at commit `ebf95fb`, under the MIT licence in the `LICENSE` file next to them.

The pipeline structure follows the [nf-core](https://nf-co.re) guidelines, but it is not an nf-core pipeline.
