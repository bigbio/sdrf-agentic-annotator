# bigbio/sdrf-agentic-annotator

[![CI](https://github.com/bigbio/sdrf-agentic-annotator/actions/workflows/ci.yml/badge.svg)](https://github.com/bigbio/sdrf-agentic-annotator/actions/workflows/ci.yml)
[![Nextflow](https://img.shields.io/badge/nextflow-%E2%89%A526.10.3-23aa62.svg)](https://www.nextflow.io/)

## Introduction

**bigbio/sdrf-agentic-annotator** annotates PRIDE datasets with [SDRF](https://github.com/bigbio/proteomics-sample-metadata). It runs the [bigbio/sdrf-skills](https://github.com/bigbio/sdrf-skills) workflow in Nextflow `agent` tasks.

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

This pipeline runs its LLM agents inside a container image, so you must pick a container
profile: `docker` for a local machine or CI, or `singularity`/`apptainer` on an HPC cluster
without root (see [docs/usage.md](docs/usage.md) for the differences).1. Make a samplesheet with one PXD accession per row:

   ```csv
   pxd
   PXD074155
   ```

2. Store the API key of your LLM provider as the Nextflow secret `LLM_KEY`:

   ```bash
   nextflow secrets set LLM_KEY <your-api-key>
   ```

   One single key is enough: the pipeline delivers it to whichever provider `--api_provider`
   selects. See [docs/usage.md](docs/usage.md) for which key value a provider expects
   (a Google/OpenAI/Anthropic key for built-in providers, or your org's gateway token for an
   OpenAI-compatible gateway such as the EBI AI Gateway).

3. Run the pipeline:

   ```bash
   nextflow run bigbio/sdrf-agentic-annotator -profile docker --input samplesheet.csv --outdir <OUTDIR>
   ```

   On an HPC node, use `-profile singularity` (or `-profile apptainer`) instead of `docker`.

To test the pipeline with one PXD, use `-profile test,docker`.

### Refine mode

`--refine` refines an SDRF that already exists in
[bigbio/sdrf-annotated-datasets](https://github.com/bigbio/sdrf-annotated-datasets) and only
accepts the refined version if it is strictly better annotated (same independent review, scored
on verdict/confidence + coverage, with coverage not worse). The samplesheet can give a
`ref_sdrf` path per PXD, or the pipeline downloads the existing SDRF from `sdrf-annotated-datasets`
with `sdrf-tools curated`.

```bash
nextflow run bigbio/sdrf-agentic-annotator -profile docker \
    --input refine.csv --outdir <OUTDIR> --refine
```

The chosen SDRF (refined if accepted, otherwise the existing one) is published per PXD, with a
`<PXD>.refine_verdict.json` explaining the decision. See [docs/usage.md](docs/usage.md) (§ Refine
mode) and [docs/output.md](docs/output.md).

See [docs/usage.md](docs/usage.md) for all options and [docs/output.md](docs/output.md) for the output files.

## Credits

bigbio/sdrf-agentic-annotator was originally written by Jonas Scheid (as
jonasscheid/nf-agent-sdrf) and is maintained in the bigbio organisation. The annotation and
review logic comes from [bigbio/sdrf-skills](https://github.com/bigbio/sdrf-skills). The skills
in `modules/local/*/skills/` are copies of bigbio/sdrf-skills at commit `ebf95fb`, under the
MIT licence in the `LICENSE` file next to them.

The pipeline structure follows the [nf-core](https://nf-co.re) guidelines, but it is not an nf-core pipeline.
