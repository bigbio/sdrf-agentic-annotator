# sdrf-agentic-annotator

> **Picking up the project?** Start with [docs/ROADMAP.md](docs/ROADMAP.md) — the state of play, what
> to build first, and the ordered backlog. Then [DEVELOPER.md](DEVELOPER.md) (architecture,
> conventions, SDRF domain traps) and [docs/INTEGRATION.md](docs/INTEGRATION.md) (combining with
> sdrf-skills).

An agentic harness for producing and curating **SDRF-Proteomics** files for PRIDE datasets.
It discovers candidate datasets, gathers evidence (deposited SDRF, publication text, empirical
signals from raw spectra), scores metadata coverage, drafts an SDRF with an LLM in a validate →
repair loop, grounds ontology terms, and gates the result before it is contributed.

The core is **model-agnostic and headless-testable**: every stage takes injected callables
(`generate(messages) -> text`, `validate(text) -> {errors, warnings}`, evidence providers), so the
logic is unit-tested with fakes and the real backends wire in at the edge.

## Model benchmark

[`benchmarks/sdrf-model-bench/`](benchmarks/sdrf-model-bench/) measures how well Claude models write
SDRFs with and without the sdrf-skills workflow, scored against curated references; results and
figures are in its [RESULTS.md](benchmarks/sdrf-model-bench/RESULTS.md).

## Layout (`src/sdrf_agentic_annotator/`)

| area | modules |
|---|---|
| discovery / harvest | `discovery`, `harvester`, `fetcher`, `ledger` |
| evidence & coverage | `evidence`, `coverage`, `template`, `template_snapshots` |
| drafting & repair | `prompt`, `draft`, `pipeline`, `expand` |
| curation & grounding | `curate`, `ground`, `ptms`, `normalizer`, `merger` |
| validation | `validator`, `fastvalidate`, `review` |
| enrichment | `techrefine` |
| LLM providers | `llm` |
| orchestration | `orchestrator`, `batch`, `run` |

## LLM providers (`llm.py`)

Downstream stages only need a `generate(messages) -> text` callable. Pick one via `get_generate`:

```python
from sdrf_agentic_annotator.llm import get_generate

# EBI-internal PRIDE LLM service (no external tokens)
generate = get_generate("pride-internal")

# or any OpenAI-compatible endpoint (e.g. a vLLM server hosting Qwen)
generate = get_generate("openai", base_url="http://vllm:8000/v1", model="Qwen2.5-32B")
```

## Tiering

Datasets are routed by coverage: a clean, high-coverage dataset goes to the cheap **qwen** tier;
one with unfillable required columns or low coverage escalates to the stronger **claude** tier for
refinement.

## Develop

```bash
pip install -e ".[dev]"
pytest -q
```
