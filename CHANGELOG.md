# bigbio/sdrf-agentic-annotator: Changelog

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
- `singularity` and `apptainer` profiles: run the pi agent runner image under
  Singularity/Apptainer on an HPC cluster without root, with the same `--models_json`
  bind-mounting (`-B`) as the `docker` profile.
- `--refine` refine mode: takes the existing SDRF for each PXD (from an optional `ref_sdrf`
  path in the samplesheet, or fetched from bigbio/sdrf-annotated-datasets), re-annotates it
  seeded on that baseline, runs the same coverage + adversarial review on both, and only accepts
  the refined version if it is strictly better (verdict/confidence + coverage not worse);
  otherwise it keeps the original. Adds `SDRF_REFINE`, `SDRF_FETCH_BASELINE` and `REFINE_VERDICT`,
  `refine_summary.tsv` and `<PXD>.refine_verdict.json`.

### `Changed`

- Documentation rewritten to make per-provider API keys clear: one `LLM_KEY` secret is
  delivered to the runner over RPC, and what its value must be depends on the provider type
  (a built-in provider key such as Google, or an OpenAI-compatible gateway token such as the
  EBI AI Gateway). Includes worked examples for both.
- Repository and manifest renamed from `jonasscheid/nf-agent-sdrf` to
  `bigbio/sdrf-agentic-annotator`.
- Runner image relocated from `ghcr.io/jonasscheid/nf-agent-sdrf:dev` to
  `ghcr.io/bigbio/sdrf-agentic-annotator:dev`; CI publishes the new path on merge
  (`.github/workflows/docker.yml` pushes to `ghcr.io/<repo>`).
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

### `Fixed`

Audit findings from [#12](https://github.com/bigbio/sdrf-agentic-annotator/issues/12):

- A samplesheet without a `ref_sdrf` column, or with an empty `ref_sdrf`, failed at startup
  with ``Argument of `file()` function cannot be empty``. This broke annotate mode and the
  `test` profile.
- Refine mode crashed when it published `<PXD>.refine_verdict.json`.
- `--max_revise 2` took the round-1 verdict as final and then crashed before writing `summary.tsv`.
- `--revise false`, `--refine false` and `--exit_on_review_fail false` given on the command line
  arrived as the string `'false'` and acted as `true`.
- `SDRF_COVERAGE` counted search, result and peak-list files in the deposit, so a complete SDRF
  scored below 1 (0.317 on PXD058436). It now counts RAW files, or peak lists if there are no RAW
  files. Its fallback skipped PRIDE's first page of files, and a PRIDE outage was reported as
  `not_verifiable` without a retry.
- `--max_parallel` did not limit the agents, which only read the `agent` config scope.
- A review report the pipeline could not parse, such as JSON in a markdown code fence, crashed
  the run; a lower-case `pass` counted as FAIL. A PASS without a confidence escaped `--confidence_gate`.
- Refine mode reviewed and published the agent's copy of the baseline instead of the input file,
  passed no evidence manifest to `SDRF_REVISE`, dropped a failed refined review when revise was
  off, and read `refined_verdict` as the final verdict for warnings and `--exit_on_review_fail`.
  `refine_summary.tsv` has a new `final_verdict` column.
- Revised files were published in `<PXD>/revised/revised/`, and a kept refine baseline as
  `<PXD>/baseline/<PXD>.baseline.sdrf.tsv`. Revise round 2 now goes to `<PXD>/revised_2/`, and refine
  mode publishes the chosen SDRF's evidence manifest, review and coverage report next to it.
- New key-free CI job with nf-test unit tests and tests for `bin/sdrf_coverage.py`.

### `Added` (coverage module internals)

- `SDRF_COVERAGE` prefers the PRIDE `/files/all` endpoint (single call) and falls
  back to the paginated `/files` (<=100/page); multi-file SDRF cells are split on
  commas before matching. The check lives in `bin/sdrf_coverage.py`.
