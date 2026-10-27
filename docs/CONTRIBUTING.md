# bigbio/sdrf-agentic-annotator: Contributing

Contributions are welcome. Open an issue first for a large change.

## Workflow

1. Fork the repository and make a branch from `main`.
2. Make the change. Keep the code in the style of the code around it.
3. Run the checks below.
4. Add a line to `CHANGELOG.md`.
5. Open a pull request against `main`.

## Checks

Run these commands with Nextflow 26.10.3 or later:

```bash
nextflow lint -format .
nf-test test --tag unit
nf-core pipelines lint
```

- `nextflow lint` must report no errors, and `-format` must not change files.
- The `unit` tests check the helpers and the channel logic. They run no agent and need no API key.
- The `pipeline` tests run the agents. They need the `LLM_KEY` secret and cost money, so CI runs them only on manual dispatch:

  ```bash
  nf-test test --tag pipeline --profile=+docker
  ```

## Pipeline structure

- `workflows/sdrf_agentic_annotator.nf` holds the main workflow. `--refine` selects the start (annotate, or fetch and refine) and the end (`summary.tsv`, or the refine acceptance gate).
- `subworkflows/local/` holds the shared parts: `SCORE_SDRF` (coverage and review), `REVISE_SDRF` (one revise round), `REVIEW_REVISE` (review and up to two revise rounds), `SUMMARISE_REVIEWS` (`summary.tsv`) and `REFINE_DECISION` (refine acceptance gate).
- `modules/local/` holds the agents and the plain processes. Agents cannot have a `stub:` block, so there is no `-stub` test.
- Do not change the names of the output files or the columns of `summary.tsv` without a changelog entry: other tools read them.
