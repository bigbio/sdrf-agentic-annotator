# SDRF agent

Throwaway feasibility test: Nextflow `agent` tasks that run the bigbio/sdrf-skills workflow for one PXD.

```
PXD ──► SDRF_ANNOTATE (agent, skill sdrf-annotate) ──► SDRF_REVIEW (agent, skill sdrf-adversarial-review) ──► results/<PXD>/
```

## Requirements

- Nextflow 26.10 (`NXF_VER=26.10.0`), Docker.
- The runner image `sdrf-agent-pi:0.6.0`. Build it with `docker build -t sdrf-agent-pi:0.6.0 docker/`.
  `docker/sdrf-skills` is a copy of bigbio/sdrf-skills@0fb449f with its `spec` submodule.
- A Gemini API key (AI Studio free tier), stored as the Nextflow secret `LLM_KEY`.

## Run

1. Store your API key as the Nextflow secret `LLM_KEY`:

   ```bash
   NXF_VER=26.10.0 nextflow secrets set LLM_KEY <your-api-key>
   ```

   Nextflow keeps secrets in `~/.nextflow/secrets`, outside the project folder.
   To keep the key out of your shell history, put a space before the command or read the key with `read -rs`.

2. Run the workflow for one PXD:

   ```bash
   NXF_VER=26.10.0 nextflow run main.nf --pxd <PXD accession> -with-agent-trace
   ```

To use a different LLM provider, change `apiProvider` and `model` in the `agent` scope of `nextflow.config`.

Inspect the agent runs after a run:

```bash
NXF_VER=26.10.0 nextflow lineage find type=AgentRun
```

## Gemini free tier

The free tier is enough to test one PXD. It is not enough for batches. Limits seen in October 2026:

| Limit | Value | Effect |
|---|---|---|
| Requests per day, `gemini-3.5-flash` | 20 | One annotation uses more than 20 requests. Use `gemini-3.5-flash-lite`. |
| Requests per minute, `gemini-3.5-flash` | 5 | 429 after about 10 tool calls. |
| Input tokens per minute, `gemini-3.5-flash-lite` | 250,000 | 429 during long agent runs. pi does not retry Gemini 429s, so the task fails and Nextflow restarts the agent from the beginning (`errorStrategy` in `nextflow.config`). |
| Overloaded models | 503 | pi retries without output, up to the retry settings in `nextflow.config`. Test a model with curl first. |

Quotas are per model, so a different model has its own quota.
Keys that start with `AQ.` can fail with `401 ACCESS_TOKEN_TYPE_UNSUPPORTED`. If that happens, create a new key.

## Layout

- `modules/sdrf_annotate/` agent module with a vendored copy of `skills/sdrf-annotate`.
- `modules/sdrf_review/` agent module with a vendored copy of `skills/sdrf-adversarial-review`.
- `docker/Dockerfile` pi runner image plus `sdrf-tools` and `parse_sdrf`.
