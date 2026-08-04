# Developer Guide — sdrf-agentic-annotator

This guide is for a developer taking over the project. It explains the mental model, the code
layout, the non-negotiable conventions, how to run and test, and how to extend each part.

Read this once end-to-end before changing code. The domain (SDRF-Proteomics) has silent-corruption
traps; the **Domain invariants** section is the part you cannot skip.

---

## 1. What it does

Given a proteomics dataset accession (usually a PRIDE `PXD…`), the project produces a valid
**SDRF-Proteomics** file (sample-and-data-relationship metadata) with as little human effort as
possible. For each dataset it:

1. **Discovers / harvests** candidate accessions and records them in a work ledger.
2. **Gathers evidence** — the deposited SDRF (if any), publication text, and empirical signals from
   the raw spectra — and **scores metadata coverage**.
3. **Routes** the dataset to a cheap or a strong LLM tier based on that coverage.
4. Either **normalizes** an existing deposited SDRF, or **drafts** a new one with an LLM in a
   *validate → repair* loop.
5. **Grounds** ontology terms, applies deterministic curation fixes, optionally enriches from raw
   spectra, and **validates** the result before it is contributed.

Two things make the codebase what it is: it is **model-agnostic** (an LLM is just an injected
callable) and **headless-testable** (every stage takes injected dependencies, so the logic is unit
-tested with fakes and no network).

---

## 2. Mental model / architecture

### The unit of work is a row in a SQLite **ledger**

`ledger.py` is a work queue. Each dataset is a row with a `status` lifecycle:

```
candidate --claim--> claimed --+--> merged      (validated SDRF written to the corpus)
     ^                         |
     |                         +--> escalate     (needs a human / stronger model / more evidence)
     +----reclaim_expired------+                 (a claim whose lease expired is retried)
```

Workers `claim(worker_id, n, lease_seconds, now)` a batch, process them, and set a terminal status.
A crash or network blip just lets the lease expire; `reclaim_expired` puts the row back to
`candidate`. This is what makes batch runs restartable and safe to run in parallel across workers.

### Two processing paths

`orchestrator.run_loop` drives a batch. For each claimed accession it fetches the (normalized)
deposited SDRF via an injected `get_sdrf_text(accession)`:

- **deposited SDRF exists** → `process_ready_sdrf` normalizes + validates it; clean → `merged`.
- **no deposited SDRF** (`get_sdrf_text` returns `None`) → `escalate`: the dataset needs the
  **drafter** (`pipeline.draft_dataset`), which builds a prompt from evidence and runs an LLM.

### The drafter is a validate → repair loop

`pipeline.draft_dataset(accession, messages, generate, validate, …)`:

```
messages ──▶ run_repair_loop(generate, validate)     # draft.py: generate → validate → feed the
   │             │                                    #   *specific* errors back → regenerate,
   │             ▼                                     #   until clean or max_iters
   │         techrefine_fn(acc, text)   (optional)     # empirical instrument/tolerances/mods from raw
   │             ▼                                     #   spectra (techsdrf), Thermo-only, per family
   └────────▶ refine_fn(text)           (optional)     # ground/strip ontology accessions
                 ▼
             {text, passed, stages}                    # `stages` records what each step changed
```

Everything the loop needs — `generate(messages) -> str`, `validate(text) -> {errors, warnings}`,
`techrefine_fn`, `refine_fn` — is **passed in**. That is why the loop is unit-tested with a fake
model that returns canned SDRF text.

---

## 3. Repo layout (`src/sdrf_agentic_annotator/`)

| group | modules | responsibility |
|---|---|---|
| **discovery** | `discovery`, `harvester`, `fetcher`, `ledger` | find candidate accessions; fetch a dataset into a `Bundle`; persist work state |
| **evidence** | `evidence`, `coverage`, `batch`, `template`, `template_snapshots` | gather evidence, score coverage, split a run into qwen/claude tiers |
| **drafting** | `prompt`, `draft`, `pipeline`, `expand` | build the LLM prompt; the repair loop; compose stages; sample-level annotate + expand large datasets |
| **curation** | `curate`, `ground`, `ptms`, `normalizer`, `merger` | deterministic fixes; resolve/strip accessions; PTM formatting; normalize deposited SDRFs; merge |
| **validation** | `validator`, `fastvalidate`, `review` | in-process structural + schema validation; review gate |
| **enrichment** | `techrefine` | wrap `techsdrf refine` (empirical columns from raw spectra) |
| **LLM** | `llm` | `generate(messages) -> text` providers (`pride-internal`, `openai`) |
| **orchestration** | `orchestrator`, `run`, `models` | the batch loop; CLI entry point; `Bundle`/`Verdict` dataclasses |

`template_snapshots.py` is **generated** (resolved SDRF template columns: name, requirement,
na-allowed). Do not hand-edit it; regenerate it from the template source.

---

## 4. Core design principles (do not break these)

1. **Model-agnostic.** Downstream code never imports an LLM SDK. It takes `generate(messages) ->
   text`. New backends go in `llm.py` behind `get_generate(provider, **kw)`.
2. **Dependency injection at the edges.** Network, the model, the cluster tool, the clock (`now`) —
   all injected. `evidence.build_evidence(accession, cache_dir, **providers)` and
   `run_loop(..., get_sdrf_text=…, now=…)` are the pattern. This is why the suite runs offline.
3. **Deterministic SDRF editing on raw tab lines.** See invariants below — this is the #1 source of
   silent corruption.
4. **Every stage returns a record of what it changed** (`stages` in `draft_dataset`, `changes`
   lists in curate/ground). Observability is part of the contract; keep it.

---

## 5. SDRF domain invariants (silent-corruption class — wrong output, no exception)

These produce a file that *looks* fine and even validates, but is wrong. Internalize them.

- **NEVER write an SDRF with `pandas.to_csv`.** pandas mangles the repeated column headers SDRF
  relies on (it appends `.1`, `.2`). SDRF **intentionally repeats** column names — multiple
  `comment[modification parameters]` (one per mod) and multiple `comment[sdrf template]`. Read/edit
  as **raw tab-separated lines**, changing only the target cells, and preserve the header verbatim.
  Every deterministic module (`curate`, `ground`, `ptms`, `expand`, `normalizer`) already does this
  — follow the same pattern.
- **Reserved words** for missing data are exactly `not available` and `not applicable` — never
  `N/A`, `NA`, `unknown`. Which one is legal is per-column (template `allow_*` flags).
- **Modification format**: `NT=name;AC=UNIMOD:id;TA=residue;MT=Fixed|Variable`. A positional value
  (`Protein N-term`) goes in `PP=`, not `TA=`. `ptms.py` owns this.
- **UNIMOD is easy to swap**: `UNIMOD:1 = Acetyl`, `UNIMOD:21 = Phospho`. Ground accessions against
  the ontology; never trust a model-guessed accession (`ground.py`).
- **Coordinate uniqueness**: `(source name, biological replicate, technical replicate, fraction
  identifier)` must be unique per row. `expand.py` guarantees this when expanding sample-level rows
  to per-file rows; the validator's collision check enforces it.
- **File-type priority**: an SDRF must reference vendor-native **raw** files, not peak lists /
  result tables. `expand.is_raw_data_file` filters supplementary tables mislabeled with a raw
  extension.
- **Ontology terms carry label + accession** (`NT=…;AC=…`) and the two must agree. Grounding
  resolves the accession for a label; it does not invent labels.

If you add a new SDRF-editing function, add a test that asserts the header is byte-for-byte
preserved and duplicate columns survive.

---

## 6. Setup & everyday workflow

Requires Python ≥ 3.11.

```bash
pip install -e ".[dev]"     # editable install + pytest
pytest -q                   # full suite, offline, ~20s
pytest tests/test_llm.py -q # one module
```

- `pyproject.toml` sets `pythonpath = ["src"]`, so `import sdrf_agentic_annotator…` works in tests
  without installing.
- The suite must stay **green and offline**. Any test that would hit the network mocks the client
  (see `tests/test_llm.py`) — never add a test that calls PRIDE/OLS/the LLM live.

---

## 7. Running

### CLI batch (`run.py`)

```bash
python -m sdrf_agentic_annotator.run \
  --accessions-file accessions.txt \   # one PXD per line
  --corpus /path/to/output-corpus \    # where validated SDRFs are written
  --db /path/to/ledger.sqlite \        # the work ledger (created if absent)
  --worker worker-1 \                  # worker id (for parallel runs)
  --max 25                             # datasets to claim this invocation
```

It harvests the accessions into the ledger, then runs one `run_loop` pass and prints a JSON summary
(`{harvested, claimed, merged, escalate, errors}`). Re-run to process the next batch; multiple
workers with distinct `--worker` ids can run concurrently against the same `--db`.

### LLM providers (`llm.py`)

```python
from sdrf_agentic_annotator.llm import get_generate

generate = get_generate("pride-internal")                 # EBI-internal PRIDE LLM, no tokens
generate = get_generate("openai", base_url="http://vllm:8000/v1", model="Qwen2.5-32B")
```

- **`pride-internal`** posts to the internal PRIDE LLM service. It is **EBI-network only** and must
  **bypass the proxy** (the client sets `session.trust_env = False`, equivalent to
  `curl --noproxy '*'`). It takes a single `query` string, so chat messages are flattened.
- **`openai`** targets any OpenAI-compatible `/chat/completions` endpoint — e.g. a vLLM server
  hosting Qwen (the historical "qwen tier" backend).

### Cluster (Codon / SLURM)

The heavy stages — LLM drafting on GPU (vLLM + Qwen) and empirical enrichment (`techrefine` →
`techsdrf refine`, which reads raw spectra) — run on the EBI Codon cluster. `techrefine` is
Thermo-only, processes one representative subset per instrument name-family, and needs its own conda
env (pyOpenMS + ThermoRawFileParser). Keep raw-file downloads bounded.

---

## 8. Testing conventions

- **Mock at the edge, not the middle.** Inject a fake `generate`/provider/`get_sdrf_text` and assert
  on the deterministic logic. `tests/test_draft.py` drives the repair loop with a scripted fake
  model; `tests/test_llm.py` mocks the HTTP session.
- **Deterministic modules get exact-output tests.** For any SDRF transform, assert the resulting tab
  lines, that the header is unchanged, and that repeated columns are preserved.
- **No network, no clock, no randomness** in tests. Time is injected (`now`); there is no reliance on
  wall-clock or RNG.
- Run `pytest -q` before every commit; keep it green.

---

## 9. How to extend

**Add an LLM backend** — implement `def my_generate(messages, *, …) -> str` in `llm.py`, register it
in `get_generate`, and add a mocked test. Downstream needs no changes.

**Add a drafter stage** — add an optional injected callable to `pipeline.draft_dataset`, run it after
the loop, and record its result under `stages`. Keep it optional (default `None`) so existing callers
and tests are unaffected.

**Add an evidence source** — add a provider function `(cache_dir, accession) -> value | None` and pass
it into `evidence.build_evidence(**providers)`; give it a cache-file default so it is testable
offline.

**Add a deterministic curation fix** — add a function to `curate.py` that takes raw SDRF text and
returns `(new_text, changes)`, editing only the target cells on raw tab lines. Wire it into the
curate sequence and add an exact-output test.

**Change routing** — coverage/tier logic lives in `coverage.py` (`route(report) -> "qwen"|"claude"`).
Adjust the score threshold / hard-gap rules there; it is pure and unit-tested.

---

## 10. External services

| service | used for | notes |
|---|---|---|
| **PRIDE Archive API** | project metadata, file lists, deposited SDRF | `fetcher`; REST fallbacks exist for MassIVE-backed PXDs |
| **OLS (Ontology Lookup Service)** | resolve/verify ontology accessions | `ground`; validation resolves label↔accession |
| **Internal PRIDE LLM** | drafting/curation without external tokens | `llm.pride-internal`; EBI-network + proxy-bypass only |
| **techsdrf** | empirical columns from raw spectra | `techrefine`; Thermo-only, cluster, own conda env |
| **sdrf-skills** | agent workflows, MCP tools, adversarial review gate | the strong ("claude") tier + tool/evidence layer — see [docs/INTEGRATION.md](docs/INTEGRATION.md) |

---

## 11. Contribution workflow

- Branch off `main` (`git checkout -b feat/…`); never commit straight to `main`.
- `pytest -q` green + no new lint before pushing.
- Keep commit messages and PRs factual and free of AI-assistant / tool attribution.
- One logical change per PR; update this guide when you change an interface or a convention.

---

## 12. Known limitations / good first tasks

- **Large multiplexed datasets** (hundreds of TMT files) rely on `expand.py` (annotate sample groups,
  expand to per-file rows); edge cases in fraction/replicate parsing are worth hardening.
- **`techrefine` at scale** is proven but download-bounded; batching/quota logic could be improved.
- **Publication text mining** for hard gaps (Europe PMC full text) is a coverage lever that is only
  partially wired.
- The `qwen` / `claude` tier names are routing labels; when the internal LLM becomes the default
  backend, revisit the tiering so provider and tier are decoupled.
