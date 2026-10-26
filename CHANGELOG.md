# jonasscheid/nf-agent-sdrf: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v0.1.0dev - [unreleased]

[#16](https://github.com/jonasscheid/nf-agent-sdrf/pull/16), [#17](https://github.com/jonasscheid/nf-agent-sdrf/pull/17)

### `Added`

- Samplesheet input with a list of PXD accessions, validated with nf-schema.
- `nextflow_schema.json` with input, output and agent parameters.
- `SDRF_REVISE`: one revision round when the review fails, followed by a second review.
- `summary.tsv` with the initial and final verdict of each PXD.
- `docker` and `test` profiles.
- GitHub Actions for linting, the runner image and the pipeline test.
- `SDRF_COVERAGE`: a deterministic, non-agent precheck that compares every
  `comment[data file]` in an SDRF against the PRIDE deposit file list and reports
  matched/missing files and the fraction of the deposit represented. Runs before
  every review (including each revise round) and is published as `PXD.coverage.json`.
- `confidence` (0..1) and `coverage` columns in `summary.tsv`, plus a
  `--confidence_gate` to flag low-confidence PASSes as `LOW_CONF` (still accepted).
- `--models_json` to add an OpenAI-compatible gateway as a pi provider.
- `--max_fetch_bytes`: the agents do not download remote files above this size.

### `Changed`

- The runner image clones bigbio/sdrf-skills at a fixed commit and no longer needs a copy of the bundle in the repo.
- Workflow outputs are copied, not linked, to `--outdir`.
- bigbio/sdrf-skills `ebf95fb` in the runner image and the module skills, with curated uveal-melanoma cell lines.
- The pipeline needs Nextflow 26.10.3 or later. In 26.10.0, `-preview` does not stop when the script has workflow outputs.
- The reviewer now receives the coverage report and must record a `confidence` and
  fold the coverage/subset gate into its verdict (see the review contract).
- A final review `FAIL` is treated as a content outcome, not an infrastructure
  error: the pipeline publishes outputs, warns and completes normally unless
  `--exit_on_review_fail` is set. Genuine task/infra errors still auto-retry.
- `--revise` now takes a bounded `--max_revise` (default 1 preserves the current
  single-revise behaviour); additional revise rounds are statically unrolled.
- New parameters `--coverage_min`, `--subset_mode`, `--confidence_gate`,
  `--max_revise`, `--max_parallel` and `--exit_on_review_fail`.

### `Added` (coverage module internals)

- `SDRF_COVERAGE` prefers the PRIDE `/files/all` endpoint (single call) and falls
  back to the paginated `/files` (<=100/page); multi-file SDRF cells are split on
  commas before matching.
