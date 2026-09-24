# sdrf-model-bench

Benchmarks how well language models write **SDRF-Proteomics** files for real PRIDE datasets,
with and without the [sdrf-skills](https://github.com/bigbio/sdrf-skills) workflow, and what that
costs. Every SDRF is scored against a curated reference from
[sdrf-annotated-datasets](https://github.com/bigbio/sdrf-annotated-datasets).

**Results and figures: [RESULTS.md](RESULTS.md).**

## Layout

| path | contents |
|---|---|
| `src/sdrf_model_bench/` | the benchmark: freeze evidence, run models, score, report (`sdrf-bench` CLI) |
| `tests/` | unit tests (no network, no model) |
| `data/` | the frozen 15-dataset pack (6 LFQ, 5 DIA, 4 TMT): `manifest.tsv`, `evidence/<PXD>/` (PRIDE record, file list, CC-licensed Methods text), `truth/<PXD>.reference.tsv` |
| `data-ext/` | the 6 datasets of the two collaborator benchmarks (Chengxin Dai, Jonas Scheid), same layout |
| `external/` | the collaborators' own SDRFs, scored with the same rubric (`import_external.py`) |
| `results/main/` | figures and scored runs for the 15-dataset benchmark |
| `results/collaborators/` | figures and scored runs on the collaborators' datasets |
| `models.yaml`, `pricing.yaml` | model roster and API-equivalent prices |
| `run_fast.sh` | the runner used for the published results |

## What is compared

- **Models:** Claude Opus 5, Sonnet 5, Haiku 4.5.
- **Arms:**
  - *prompt only*: one fixed prompt and the frozen evidence, then up to 2 repair turns driven by
    the validator.
  - *skills*: Claude Code with the sdrf-skills plugin, in a sandbox with no network and no MCP. It
    can use `parse_sdrf` and `sdrf-tools` (`contract`, `build`).
- **Evidence:** offline only, from the PRIDE record and the raw file list. The paper is not given.
- **Score (0–100), deterministic:**

  | part | weight | measures |
  |---|---|---|
  | validity | 20 | `parse_sdrf` |
  | completeness | 15 | columns and rows present |
  | accuracy | 50 | key fields, cell by cell, ontology-aware |
  | specificity | 15 | no needless `not available` |

  Disagreements are triaged (style only, reference fault, run wrong), and faults in the reference
  are not charged to the run. An optional LLM judge exists (`score` without `--no-judge`); it is not
  used in the published numbers.

## Run it

Requirements:
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- `parse_sdrf` (`pip install 'sdrf-pipelines[ontology]'`)
- for the skills arm: Claude Code with the sdrf-skills plugin installed

```bash
uv sync --extra dev && uv run pytest -q

# run (resumes; re-run to retry crashed runs), score, report
uv run sdrf-bench run --only sonnet-5-skills --manuscript off --data data --outputs outputs
uv run sdrf-bench score --data data --outputs outputs --out results/main/runs.jsonl --no-judge
uv run sdrf-bench report --results results/main/runs.jsonl --manuscript off --deterministic \
    --out results/main --data data

# or the whole roster, 3 runs at a time, waiting out usage limits
./run_fast.sh
```

To add another model, give it an entry in `models.yaml`:
- `provider: openai` for any OpenAI-compatible endpoint
- `provider: ollama` for a local model (always set `num_ctx`)
- `provider: custom` with `options: {callable: "module:function"}` for anything else

## Caveats

- **Agreement, not truth.** Scores measure agreement with the curators, not objective truth. A run
  can be better than the reference (the triage panel shows where).
- **Possible contamination.** The curated SDRFs are public, so models may have seen them;
  `contamination_suspect` flags suspiciously high scores on datasets with poor PRIDE metadata.
- **One replicate.** Each configuration and dataset ran once. Differences of 1–2 points are within
  run-to-run spread.
- **Harmless `leak_suspect` flags.** On skills runs, the flag also fires when Claude Code reads its
  own spill files for large tool outputs. Those reads are not reference data.
