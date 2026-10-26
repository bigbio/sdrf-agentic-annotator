# jonasscheid/nf-agent-sdrf: Usage

## Samplesheet input

Give the samplesheet with `--input`. It is a CSV file with one column, `pxd`, and one PRIDE accession per row:

```csv
pxd
PXD074155
PXD058436
```

Each accession must be unique. The pipeline validates the file against [assets/schema_input.json](../assets/schema_input.json) before it starts.

## API key

The agents read the API key from the Nextflow secret `LLM_KEY`:

```bash
nextflow secrets set LLM_KEY <your-api-key>
```

Nextflow keeps secrets in `~/.nextflow/secrets`, outside the project folder. To keep the key out of your shell history, put a space before the command.

## LLM provider and model

| Parameter | Default | Description |
|---|---|---|
| `--model` | `google/gemini-3.5-flash-lite` | Model as `<provider>/<model>`. |
| `--api_provider` | `google` | Provider of the key in `LLM_KEY`. |
| `--revise` | `true` | Revise an SDRF when its review fails, then review it again. |
| `--max_revise` | `1` | Maximum revise -> re-review rounds a dataset may go through (bounded escalation). |
| `--max_parallel` | `0` | Max agent tasks that run concurrently across the batch; `0` = unlimited. Lower it to reduce resource contention. |
| `--models_json` | none | Absolute path to a pi `models.json` that adds an OpenAI-compatible gateway as a provider. Works with the `docker` profile only. |
| `--max_fetch_bytes` | `524288000` | The agents do not download a remote file larger than this number of bytes. |

### OpenAI-compatible gateway

To use a model on an OpenAI-compatible gateway, write a pi `models.json` file. Keep this file outside the repository, for example in `runtime/`. Git ignores `runtime/`.

```json
{
  "providers": {
    "mygateway": {
      "baseUrl": "https://gateway.example.org/v1",
      "api": "openai-completions",
      "models": [
        { "id": "openai/DeepSeek-V4-Flash-0731" }
      ]
    }
  }
}
```

The key of the provider, here `mygateway`, is the provider name. The model `id` must be the model string that the gateway expects. Do not put the API key in this file. The agents get the key from the `LLM_KEY` secret.

Give the file with `--models_json`. Use the provider name in `--model` and `--api_provider`:

```bash
nextflow run jonasscheid/nf-agent-sdrf -profile docker --input samplesheet.csv --outdir <OUTDIR> \
    --models_json $PWD/runtime/models.json \
    --model mygateway/openai/DeepSeek-V4-Flash-0731 \
    --api_provider mygateway
```

The `docker` profile mounts the file read-only at `/opt/pi-config/models.json` in the agent container. Without `--models_json`, the image uses [docker/models.json](../docker/models.json). This file has no providers, so pi uses only its built-in models. For all `models.json` fields, see the [pi model documentation](https://pi.dev/docs/latest/models).

### Large remote files

The agents read the `Content-Length` of a remote file before they download it. They do not download a file larger than `--max_fetch_bytes`. For MaxQuant datasets, they use the small result files, such as `mqpar.xml`, `peptides.txt` and `evidence.txt`. They do not use `msms.txt` or raw files, because these are often many GB. If the reviewer can only verify a value from a file above the limit, it reports the value as not fully verifiable.

### Coverage / subset gate

A deterministic `SDRF_COVERAGE` step runs before every review. It compares each
`comment[data file]` in the SDRF against the PRIDE deposit file list and writes a
`PXDXXX.coverage.json` reporting matched/missing files and the fraction of the
deposit the SDRF represents. The reviewer must fold this into its verdict:

| Parameter | Default | Description |
|---|---|---|
| `--coverage_min` | `0.0` | If an SDRF represents less than this fraction (0..1) of the deposit's data files, the reviewer must treat it as an important finding unless the artifact honestly declares itself a subset. `0.0` = informational only (backward compatible). |
| `--subset_mode` | `false` | Permit a clearly-declared representative subset (e.g. a huge DIA deposit) to be accepted instead of failing on under-representation. |

### Confidence gating

Every review records a `confidence` (0..1). A PASS below the following gate is
still accepted and passed on, but flagged `LOW_CONF` in `summary.tsv` so you can
revisit it:

| Parameter | Default | Description |
|---|---|---|
| `--confidence_gate` | `0.0` | Flag PASSes with confidence below this threshold as `LOW_CONF`. `0.0` = no gating. |

### Content FAIL vs infrastructure FAIL

A dataset whose final review is `FAIL` is a *content* outcome (the SDRF did not
survive review), not an infrastructure error. By default the pipeline publishes the
outputs, logs a warning and completes normally. Only genuine task/infra errors fail
tasks (which auto-retry via `conf/base.config`):

| Parameter | Default | Description |
|---|---|---|
| `--exit_on_review_fail` | `false` | `true` makes the run exit non-zero when any dataset's final verdict is FAIL. |

### Gemini free tier

The free tier is enough to test one PXD. It is not enough for batches. Limits seen in October 2026:

| Limit | Value | Effect |
|---|---|---|
| Requests per day, `gemini-3.5-flash` | 20 | One annotation uses more than 20 requests. Use `gemini-3.5-flash-lite`. |
| Requests per minute, `gemini-3.5-flash` | 5 | 429 after about 10 tool calls. |
| Input tokens per minute, `gemini-3.5-flash-lite` | 250,000 | 429 during long agent runs. pi does not retry Gemini 429s, so the task fails and Nextflow starts the agent again from the beginning (see [#3](https://github.com/jonasscheid/nf-agent-sdrf/issues/3)). |
| Overloaded models | 503 | pi retries without output, up to the retry settings in [conf/base.config](../conf/base.config). |

Quotas are per model, so a different model has its own quota. Keys that start with `AQ.` can fail with `401 ACCESS_TOKEN_TYPE_UNSUPPORTED`. If that happens, create a new key.

## Profiles

| Profile | Description |
|---|---|
| `docker` | Runs the agents in the runner image `ghcr.io/jonasscheid/nf-agent-sdrf`. Required. |
| `test` | Annotates one PXD from [assets/samplesheet.csv](../assets/samplesheet.csv). Needs `LLM_KEY`. |

## Runner image

[docker/Dockerfile](../docker/Dockerfile) builds the runner image. It adds `sdrf-tools`, `parse_sdrf` and the sdrf-skills bundle at a fixed commit to the pi runner image. GitHub Actions builds and pushes the image to `ghcr.io/jonasscheid/nf-agent-sdrf`. To build it locally:

```bash
docker build -t ghcr.io/jonasscheid/nf-agent-sdrf:dev docker/
```

The skills in `modules/local/*/skills/` must have the same commit as `SDRF_SKILLS_REF` in the Dockerfile. Nextflow cannot load them from bigbio/sdrf-skills yet (see [#1](https://github.com/jonasscheid/nf-agent-sdrf/issues/1)).

## Agent traces

To record the agent conversations, add `-with-agent-trace`. To list the agent runs after a run:

```bash
nextflow lineage find type=AgentRun
```
