# bigbio/sdrf-agentic-annotator: Usage

## Samplesheet input

Give the samplesheet with `--input`. It is a CSV file with one column, `pxd`, and one PRIDE accession per row:

```csv
pxd
PXD074155
PXD058436
```

Each accession must be unique. The pipeline validates the file against [assets/schema_input.json](../assets/schema_input.json) before it starts.

## Refine mode

Refine mode (`--refine`) takes an SDRF that already exists in
[bigbio/sdrf-annotated-datasets](https://github.com/bigbio/sdrf-annotated-datasets) and tries to
produce a better-annotated version — but it only accepts the refined SDRF if, scored by the same
independent adversarial review as the baseline, it is strictly better. Otherwise it keeps the
original.

The refine samplesheet carries the same `pxd` column plus an optional `ref_sdrf` column (an
absolute path to the existing SDRF for that PXD):

```csv
pxd,ref_sdrf
PXD074155,/data/PXD074155.sdrf.tsv
PXD058436,
```

When `ref_sdrf` is empty, a fetch agent downloads the existing SDRF from
`bigbio/sdrf-annotated-datasets` by PXD (the `ref_sdrf` path wins when both are given).

Run it exactly like annotate mode, with `--refine`:

```bash
nextflow run bigbio/sdrf-agentic-annotator -profile docker \
    --input refine.csv --outdir <OUTDIR> --refine \
    --api_provider google --model google/gemini-3.5-flash-lite
```

How refine mode works:

1. **Baseline acquisition** — each row's baseline SDRF comes from `ref_sdrf`, or is fetched from
   `sdrf-annotated-datasets` by PXD.
2. **Seeded re-annotation** — the `SDRF_REFINE` agent treats the existing SDRF as the baseline to
   beat. It re-annotates from fresh evidence (PRIDE, Europe PMC, Cellosaurus, OLS), filling gaps
   and fixing values only when a source supports it, and validates the result. It also writes a
   baseline evidence manifest that traces the *existing* SDRF's values to sources (or lists them
   under limitations), so the baseline is scored on the same terms as the refined version.
3. **Same review for both** — the pipeline runs the deterministic `SDRF_COVERAGE` precheck and the
   independent `SDRF_REVIEW` on the baseline and on the refined SDRF. The baseline reviewed is the
   input file itself, not a copy made by the agent.
4. **Acceptance gate** — a refined SDRF is accepted only when all of these hold:
   - the refined review verdict is `PASS`,
   - the refined coverage is measurable and not worse than the baseline's, and
   - either the baseline did not `PASS` (FAIL → PASS) or the refined confidence is strictly
     higher.
   Otherwise the existing SDRF is kept. The per-PXD decision is written to
   `<PXD>.refine_verdict.json` and summarised in `refine_summary.tsv` (see
   [docs/output.md](docs/output.md)).

The `--revise` option applies to the refined version: if its first review fails, `SDRF_REVISE`
fixes it and it is re-reviewed before the gate, as in annotate mode. Refine mode revises at most
once, whatever `--max_revise` is (unless it is `0`).

## API keys and providers

The agents talk to a language model through Nextflow's `pi` runner, which runs inside the
container image. The API key never lands on disk, in the repository, or in the task
environment: the Nextflow driver passes it to the runner over an RPC channel at run time.

You register exactly one key, the Nextflow secret `LLM_KEY`, and tell the pipeline which
provider it belongs to with `--api_provider`:

```bash
nextflow secrets set LLM_KEY <your-api-key>
```

Nextflow keeps secrets in `~/.nextflow/secrets`, outside the project folder. To keep the key
out of your shell history, put a space before the command.

### What your key actually is depends on the provider type

| Provider type | `--api_provider` | `LLM_KEY` value | `models.json` needed? |
|---|---|---|---|
| Built-in provider (Google, OpenAI, Anthropic, OpenRouter, ...) | the provider name, e.g. `google` | the key that provider issues you (e.g. a Google AI Studio API key) | No — pi ships their config |
| OpenAI-compatible gateway (your org's gateway, e.g. the EBI AI Gateway) | the gateway name you register in `models.json`, e.g. `ebi` | the bearer/API token the gateway issues you | Yes — register the gateway once |

> [!NOTE]
> `--model` is `<provider>/<model>`. The `<provider>` prefix must be the same value you pass
> to `--api_provider` — for a built-in provider it is the built-in provider name, and for a
> gateway it is the provider key from your `models.json`.

### Container profile: docker vs singularity

The agents run in the runner image, so you need a container engine. On a machine with Docker
use `-profile docker`; on an HPC cluster without root use `-profile singularity` (or
`-profile apptainer`). The provider and key setup below is identical whatever profile you use.

### Example A — Google Gemini (built-in provider)

```bash
nextflow secrets set LLM_KEY <google-ai-studio-api-key>
nextflow run bigbio/sdrf-agentic-annotator -profile docker \
    --input samplesheet.csv --outdir <OUTDIR> \
    --api_provider google --model google/gemini-3.5-flash-lite
```

### Example B — EBI AI Gateway (OpenAI-compatible gateway)

Many organisations (including the EBI) front several models behind one OpenAI-compatible
gateway. You register that gateway once in a pi `models.json`, then point the pipeline at it.
Keep the file outside the repository, for example in `runtime/` (git ignores `runtime/`). Do
**not** put the API key in this file — it is delivered from the `LLM_KEY` secret at run time:

```json
{
  "providers": {
    "ebi": {
      "baseUrl": "https://api.ebi.ac.uk/<your-gateway>/v1",
      "api": "openai-completions",
      "models": [
        { "id": "openai/DeepSeek-V4-Flash-0731" }
      ]
    }
  }
}
```

- The provider key (`ebi`) is the value you pass to `--api_provider` and to the `<provider>`
  prefix of `--model`.
- The model `id` is the literal string your gateway expects; it is exactly what is sent to the
  base URL, so it must match your gateway's model name.
- `LLM_KEY` is the token your gateway issues you.

```bash
nextflow secrets set LLM_KEY <ebi-gateway-token>
nextflow run bigbio/sdrf-agentic-annotator -profile docker \
    --input samplesheet.csv --outdir <OUTDIR> \
    --models_json $PWD/runtime/models.json \
    --model ebi/openai/DeepSeek-V4-Flash-0731 \
    --api_provider ebi
```

Every profile that can run the agent container bind-mounts `--models_json` read-only at
`/opt/pi-config/models.json` (docker uses `-v`, singularity/apptainer use `-B`). Without
`--models_json`, the image uses [docker/models.json](../docker/models.json), which registers no
providers, so pi uses only its built-in models. For all `models.json` fields, see the [pi model
documentation](https://pi.dev/docs/latest/models).

### Large remote files

The agents read the `Content-Length` of a remote file before they download it. They do not download a file larger than `--max_fetch_bytes`. For MaxQuant datasets, they use the small result files, such as `mqpar.xml`, `peptides.txt` and `evidence.txt`. They do not use `msms.txt` or raw files, because these are often many GB. If the reviewer can only verify a value from a file above the limit, it reports the value as not fully verifiable.

### Coverage / subset gate

A deterministic `SDRF_COVERAGE` step runs before every review. It compares each
`comment[data file]` in the SDRF against the PRIDE deposit file list and writes a
`PXDXXX.coverage.json` reporting matched/missing files and the fraction of the
deposit the SDRF represents. That fraction counts the deposit's RAW files, or its peak lists
(mzML, MGF, ...) if it has no RAW files; search and result files are not counted. If PRIDE
cannot be reached after a few attempts, the report is `not_verifiable`. The reviewer must
fold this into its verdict:

| Parameter | Default | Description |
|---|---|---|
| `--coverage_min` | `0.0` | If an SDRF represents less than this fraction (0..1) of the deposit's data files, the reviewer must treat it as an important finding unless the artifact honestly declares itself a subset. `0.0` = informational only (backward compatible). |
| `--subset_mode` | `false` | Permit a clearly-declared representative subset (e.g. a huge DIA deposit) to be accepted instead of failing on under-representation. |

### Confidence gating

Every review records a `confidence` (0..1). A PASS below the following gate, or
without a confidence, is still accepted and passed on, but flagged `LOW_CONF` in
`summary.tsv` so you can revisit it:

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

### Revise rounds and parallelism

| Parameter | Default | Description |
|---|---|---|
| `--revise` | `true` | Revise an SDRF whose review fails, then review it again. `--revise false` skips this. |
| `--max_revise` | `1` | Number of revise rounds, `0` to `2`. A second round only runs for SDRFs whose first revision fails its review too. |
| `--max_parallel` | `0` | Maximum number of concurrent tasks of each process (each agent, such as `SDRF_ANNOTATE`, and `SDRF_COVERAGE`). `0` keeps the default of 10. Lower it to stay within provider rate limits or on a small machine. |

### Gemini free tier

The free tier is enough to test one PXD. It is not enough for batches. Limits seen in October 2026:

| Limit | Value | Effect |
|---|---|---|
| Requests per day, `gemini-3.5-flash` | 20 | One annotation uses more than 20 requests. Use `gemini-3.5-flash-lite`. |
| Requests per minute, `gemini-3.5-flash` | 5 | 429 after about 10 tool calls. |
| Input tokens per minute, `gemini-3.5-flash-lite` | 250,000 | 429 during long agent runs. pi does not retry Gemini 429s, so the task fails and Nextflow starts the agent again from the beginning (see [jonasscheid/nf-agent-sdrf#3](https://github.com/jonasscheid/nf-agent-sdrf/issues/3)). |
| Overloaded models | 503 | pi retries without output, up to the retry settings in [conf/base.config](../conf/base.config). |

Quotas are per model, so a different model has its own quota. Keys that start with `AQ.` can fail with `401 ACCESS_TOKEN_TYPE_UNSUPPORTED`. If that happens, create a new key.

## Profiles

Pick exactly one container profile (`docker`, `singularity` or `apptainer`), plus optionally
`test`. The runners are the same in every case; only the container engine differs.

| Profile | Description |
|---|---|
| `docker` | Run the agents in the runner image `ghcr.io/bigbio/sdrf-agentic-annotator` with Docker. Suitable for a local machine or CI. |
| `singularity` | Run the same runner image with Singularity (no root, no daemon). For HPC clusters. Requires Singularity on the execution node. |
| `apptainer` | Same as `singularity`, using Apptainer (the renamed Singularity). |
| `test` | Annotates one PXD from [assets/samplesheet.csv](../assets/samplesheet.csv). Needs `LLM_KEY`. Combine with a container profile, e.g. `-profile test,docker`. |

## Runner image

[docker/Dockerfile](../docker/Dockerfile) builds the runner image. It adds `sdrf-tools`,
`parse_sdrf` and the sdrf-skills bundle at a fixed commit to the pi runner image. GitHub
Actions builds and pushes the image to `ghcr.io/bigbio/sdrf-agentic-annotator`. To build it
locally:

```bash
docker build -t ghcr.io/bigbio/sdrf-agentic-annotator:dev docker/
```

The image is an OCI/Docker image. Under the `singularity`/`apptainer` profiles, the first use
pulls it from the registry and converts it to a SIF; set `NXF_SINGULARITY_CACHEDIR` (or
`NXF_APPTAINER_CACHEDIR`) to a shared directory so every compute node reuses that pull. If your
cluster cannot reach the registry, build a SIF once with

```bash
singularity build sdrf-agentic-annotator.sif docker://ghcr.io/bigbio/sdrf-agentic-annotator:dev
```

and point the profile at it, or add the cached pull into the shared cache directory.

The skills in `modules/local/*/skills/` must have the same commit as `SDRF_SKILLS_REF` in the
Dockerfile. Nextflow cannot load them from bigbio/sdrf-skills yet (see
[jonasscheid/nf-agent-sdrf#1](https://github.com/jonasscheid/nf-agent-sdrf/issues/1)). The one
local change is the `confidence` and `coverage` sections in
`sdrf_review/skills/sdrf-adversarial-review/references/review-contract.md`; keep them when you
sync the skills.

## Agent traces

To record the agent conversations, add `-with-agent-trace`. To list the agent runs after a run:

```bash
nextflow lineage find type=AgentRun
```
