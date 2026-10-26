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
  `comment[data file]` in an SDRF with the deposited runs. Runs before every review
  (including each revise round) and is published as `PXD.coverage.json`.
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
- `nextflow_function` and `nextflow_workflow` nf-tests for the summary, completion and refine helpers. A CI job runs them on every pull request; they need no API key. A refine-mode pipeline test runs on dispatch ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).

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
- The runner image copies the bigbio/sdrf-skills bundle from `ghcr.io/bigbio/sdrf-skills:sha-5f5966b`
  instead of cloning it, and installs `sdrf-tools` and `parse_sdrf` at that image's package versions.
  It sets `SDRF_SKILLS_ROOT` and ships the `parse_sdrf` ontology cache for offline, non-root runs
  ([#11](https://github.com/bigbio/sdrf-agentic-annotator/pull/11)).
- Workflow outputs are copied, not linked, to `--outdir`.
- bigbio/sdrf-skills `ebf95fb` in the runner image and the module skills, with curated uveal-melanoma cell lines.
- Refine mode reuses the sdrf-skills tools: `SDRF_FETCH_BASELINE` is a plain process that runs
  `sdrf-tools curated` instead of an agent, and fails when the PXD has no curated SDRF.
  `SDRF_REFINE` requests `existing annotation: fix` from the `sdrf-annotate` skill and links the
  skill of `SDRF_ANNOTATE` instead of a copy ([#8](https://github.com/bigbio/sdrf-agentic-annotator/pull/8)).
- An empty `ref_sdrf` in the refine samplesheet no longer stops the run with `file()` on an empty path.
- The pipeline needs Nextflow 26.10.3 or later. In 26.10.0, `-preview` does not stop when the script has workflow outputs.
- The reviewer now receives the coverage report and must record a `confidence` and
  fold the coverage/subset gate into its verdict (see the review contract).
- A final review `FAIL` is treated as a content outcome, not an infrastructure
  error: the pipeline publishes outputs, warns and completes normally unless
  `--exit_on_review_fail` is set. Genuine task/infra errors still auto-retry.
- `SDRF_ANNOTATE`, `SDRF_REVIEW` and `SDRF_REVISE` use the unattended mode, external-review hand-off and output contract of bigbio/sdrf-skills `5f5966b` instead of their own overrides. The reviewer receives `<PXD>.validation.txt` and `evidence/`; the revise agent edits `samples.tsv` and `technical.tsv` ([#9](https://github.com/bigbio/sdrf-agentic-annotator/pull/9)).
- `--revise` now takes a bounded `--max_revise` (default 1 preserves the current
  single-revise behaviour); additional revise rounds are statically unrolled.
- `SDRF_COVERAGE` runs `sdrf-tools fetch` and `sdrf-tools audit-existing --json` from
  `ghcr.io/bigbio/sdrf-skills:sha-1ea3d2f` instead of its own PRIDE query. `<PXD>.coverage.json` is the
  `coverage` block of that report. Its `fraction` counts deposited runs only, and Bruker `.d`/`.d.zip`
  names match ([#14](https://github.com/bigbio/sdrf-agentic-annotator/pull/14)).
- New parameters `--coverage_min`, `--subset_mode`, `--confidence_gate`,
  `--max_revise`, `--max_parallel` and `--exit_on_review_fail`.
- `SDRF_ANNOTATE` and `SDRF_REVISE` name the external-review hand-off and the status `REVIEW_PENDING_EXTERNAL` in their requests ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).
- The review and coverage helpers are functions of the utils subworkflow, shared by both workflows ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).
- `SCORE_SDRF` runs the coverage precheck and the review for both workflows. In refine mode, the reviewer of a revised SDRF now also gets its validation output ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).
- `REVISE_SDRF` runs one revise round and `REVIEW_REVISE` runs the review and up to two revise rounds. `--max_revise` takes 0 to 2; the schema rejects other values ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).
- Refine mode scores the refined SDRF with `SCORE_SDRF` and revises it with `REVIEW_REVISE` ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).

### `Fixed`

- With `--max_revise 2`, `summary.tsv` takes the final verdict from the last revise round. Before, a PXD with two revise rounds stopped the run ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).
- In refine mode, the completion check reads the verdict of the chosen SDRF. Before, it read `refined_verdict`, so a kept baseline gave a wrong warning and `--exit_on_review_fail` could stop the run ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).
- In refine mode, `SDRF_REVISE` gets the evidence manifest of the refined SDRF. Before, it got no manifest and the task failed when the refined review failed ([#NNN](https://github.com/bigbio/sdrf-agentic-annotator/pull/NNN)).
