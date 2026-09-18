# sdrf-model-bench

This benchmark measures how well a language model writes an **SDRF-Proteomics** file for a real
PRIDE dataset, and what that costs in tokens, money and time. Each output is scored against a
curated SDRF from [sdrf-annotated-datasets](https://github.com/bigbio/sdrf-annotated-datasets).

## What is measured

| axis | levels |
|---|---|
| model | any: Claude, local Ollama models, OpenAI-compatible endpoints, or your own function |
| arm | **raw**: one fixed prompt, then up to 2 repair turns driven by the validator. **skills**: Claude Code with the sdrf-skills plugin (Claude only) |
| manuscript | **on**: the paper's Methods section is in context. **off**: repository metadata and raw file names only |
| quantification | TMT, LFQ, DIA (4 datasets each) |
| PRIDE metadata | rich or poor, 2 of each per quantification type |

That makes 12 datasets × 2 manuscript conditions = **24 runs per model**.

**Score (0–100)** = 0.8 × deterministic + 0.2 × LLM judge.

The deterministic part is:
- 20% validity (`parse_sdrf`)
- 15% completeness (columns and rows present)
- 50% accuracy (key fields cell by cell, ontology-aware)
- 15% specificity (penalises "not available" where the curators found a value)

The judge (sonnet-5, run 3 times, median taken, blind to the model name) grades factor values,
design fidelity and free text against the reference. Both parts are stored separately, and
`--no-judge` gives deterministic-only scores.

## Everything is frozen

`data/` contains everything a model is allowed to see, captured once, plus the answer key:

```
data/manifest.tsv                 the 12 datasets, quantification type, PRIDE tier, licence
data/evidence/<PXD>/pride.json    PRIDE project record
data/evidence/<PXD>/files.json    raw file names
data/evidence/<PXD>/manuscript.txt  Methods + sample legends (CC-licensed papers only)
data/truth/<PXD>.sdrf.tsv         the curated reference (never shown to models)
```

Runs never touch the network for evidence. That's what keeps your numbers comparable with ours.

## Quick start: benchmark your model

Requirements:
- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/)
- `parse_sdrf` from sdrf-pipelines: `pip install sdrf-pipelines`. The first validation downloads ontology caches.

```bash
tar xzf sdrf-model-bench-v1.tar.gz && cd sdrf-model-bench
uv sync --extra dev && uv run pytest -q          # sanity check, no network, no model
```

**1. Add your model to `models.yaml`.** Pick the matching provider.

```yaml
# an OpenAI-compatible server (vLLM, LiteLLM, TGI, hosted APIs)
- {id: mymodel-raw, provider: openai, model: my-model-name, arm: raw, context_window: 131072,
   options: {base_url: "http://localhost:8000/v1", api_key_env: MY_API_KEY}}

# a local Ollama model: always set num_ctx, because Ollama silently truncates without it
- {id: llama-70b-raw, provider: ollama, model: "llama3.3:70b", arm: raw, context_window: 131072,
   options: {num_ctx: 40960}}

# anything else: a Python function in your own module
- {id: mymodel-raw, provider: custom, model: my-model, arm: raw, context_window: 128000,
   options: {callable: "my_provider:generate"}}
```

A custom function takes OpenAI-style `messages`, plus `max_output_tokens` if it declares it (or
`**kwargs`). It returns either the reply text, or `(text, {"input_tokens": n, "output_tokens": m})`
so that your token counts appear on the slide.

**2. Run, score and report.**

```bash
uv run sdrf-bench run --only mymodel-raw      # 24 runs; re-run the same command to resume or retry
uv run sdrf-bench score --no-judge            # add the judge if you have ANTHROPIC_API_KEY
uv run sdrf-bench report                      # results/slide.png, summary.tsv, backup plots
```

**3. Send us** the folder `outputs/mymodel-raw/`. We'll score it centrally with the judge so it
appears on the shared slide. If you'd rather not use our runner, see [SUBMISSION.md](SUBMISSION.md).

## Fairness rules built into the runner

- Every raw model gets the same system prompt, the same evidence, the same 24k-token evidence
  budget, the same validator feedback, and the same output budget: max(4096, 2 × the size of a
  correct answer).
- Local models run at temperature 0. Opus 5 and Sonnet 5 don't accept a temperature, so they use
  their defaults.
- The skills arm runs Claude Code with `--bare`, a copy of the plugin with its bundled annotations
  removed, no MCP servers and no web tools, and read access denied under `$HOME`. Any file access
  outside the workspace flags the run as `leak_suspect`.
- **Flags** (listed in `summary.tsv`, and shown as ⚠ on the slide):
  - `context_limited`: the prompt plus a correct answer doesn't fit the model's context
  - `failed`: no SDRF was produced
  - `contamination_suspect`: an unusually high score without the manuscript on a poor-metadata
    dataset
  - `leak_suspect`: file access outside the workspace (skills arm)

## Known limitations

- The curated SDRFs are public, and PRIDE republishes them as `*_community_annotated.sdrf.tsv`.
  Models may have seen them during training. The `contamination_suspect` flag is a signal, not proof.
- TMT is scarce in the curated corpus (83 channel-level files in about 9,000 curated SDRFs), so
  TMT uses a 100-row cap where LFQ and DIA use 60.
- The PRIDE quality tiers are relative to this pool. Datasets with an open-access paper tend to
  have reasonable PRIDE records, so "poor" means "poorer than the others".
- Ontology credit is exact accession (1.0) or matching label (0.5). Parent and child terms get no
  credit.

## For maintainers

```bash
uv run sdrf-bench select --datasets ../sdrf-annotated-datasets/datasets   # re-select: creates a NEW benchmark version
uv run sdrf-bench run                                                      # full roster (needs ANTHROPIC_API_KEY, ollama)
uv run sdrf-bench pack                                                     # sdrf-model-bench-v1.tar.gz for collaborators
```

Design notes: `docs/design/2026-09-18-model-benchmark-design.md` in the parent repository.
