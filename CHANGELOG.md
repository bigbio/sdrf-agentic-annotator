# jonasscheid/nf-agent-sdrf: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v0.1.0dev - [unreleased]

### `Added`

- Samplesheet input with a list of PXD accessions, validated with nf-schema.
- `nextflow_schema.json` with input, output and agent parameters.
- `SDRF_REVISE`: one revision round when the review fails, followed by a second review.
- `summary.tsv` with the initial and final verdict of each PXD.
- `docker` and `test` profiles.
- GitHub Actions for linting, the runner image and the pipeline test.

### `Changed`

- The runner image clones bigbio/sdrf-skills at a fixed commit and no longer needs a copy of the bundle in the repo.
- Workflow outputs are copied, not linked, to `--outdir`.
- The pipeline needs Nextflow 26.10.3 or later. In 26.10.0, `-preview` does not stop when the script has workflow outputs.
