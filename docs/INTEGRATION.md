# Integrating with sdrf-skills

`sdrf-agentic-annotator` (this repo) and [`bigbio/sdrf-skills`](https://github.com/bigbio/sdrf-skills)
are **two layers of one system**, not competing tools.

| | **sdrf-agentic-annotator** | **sdrf-skills** |
|---|---|---|
| Role | orchestration + scale | per-dataset intelligence + tools + review |
| Shape | Python package, headless, deterministic | `SKILL.md` agent workflows + `tools/` + `mcp/` + `spec/` |
| Owns | ledger work-queue, batch/parallel workers, tiered routing, the deterministic curate→ground→validate spine, the validate→repair loop | domain knowledge (`sdrf-annotate`, `sdrf-knowledge`), MCP tools (PRIDE/OLS/PMC), the adversarial **review gate**, and the **spec source of truth** (`TERMS.tsv` + template YAMLs) |
| Strength | throughput, restartability, reproducibility | quality on one hard dataset, tool access, agent/human-in-the-loop review |

> **In one line:** sdrf-skills is the *brain + tools + reviewer* for one dataset; this repo is the
> *factory* that runs thousands and knows when to call the brain.

The harness is model-agnostic and injects a callable at **every edge**, and sdrf-skills provides
exactly those capabilities — so they meet at the injection points.

## The seam: harness edge ← sdrf-skills capability

| harness injects… | filled by sdrf-skills |
|---|---|
| `fetcher` / `get_sdrf_text` (PRIDE project, files, deposited SDRF) | MCP `get_project_details`, `get_project_files`; `tools/massive_raw_files.py` |
| evidence providers (paper text, PDF) | MCP `get_pdf_by_unpaywall`, `get_full_text_article`/`_section`, `get_article_metadata` |
| `ground` (resolve/verify OLS accessions) | `tools/ols_client.py`; MCP `searchClasses`, `getChildren`, `search` |
| `curate` / cell-line resolution | `tools/cellline_db.py`, `tools/column_ontology_map.py`; skill `sdrf-cellline` |
| `validate(text)` | `tools/completeness.py`, `tools/hallucination.py`, `tools/sdrf_parser.py`; skill `sdrf-validate` |
| contribution gate | `tools/review_gate.py` (hash-bound receipts); skill `sdrf-adversarial-review` |
| `generate(messages)` for the **strong tier** | the `sdrf-annotate` skill run by an agent (reads the paper, uses MCP tools) |
| `techrefine` | both wrap `techsdrf`; skill `sdrf-techrefine` |
| template spec (`template_snapshots.py`) | `spec/` submodule: `TERMS.tsv` + `sdrf-templates` |

## Combined architecture

```
                 sdrf-agentic-annotator  (queue + scale + deterministic spine)
                 ┌───────────────────────────────────────────────────────────┐
   accessions ──▶│ ledger ─▶ evidence+coverage ─▶ route(qwen|claude) ─────────┐│
                 │                                        │                   ││
                 │   qwen tier (bulk):                    │  claude tier:     ││
                 │   normalize/draft with internal LLM,   │  hand off  ───────┼┼──▶ sdrf-skills
                 │   curate → ground → validate           │  (handoff.py)     ││    /sdrf:annotate
                 │        │                               │      │            ││    + MCP tools
                 └────────┼───────────────────────────────┼──────┼───────────┘│    + paper reading
                          ▼                               │      │             │
        shared gate: sdrf-skills review_gate / adversarial-review              │
                          │                               │      │             │
                          ▼                               ▼      ▼             │
               ledger row → merged  ◀── ingest completed hand-off ◀────────────┘
```

Easy / high-coverage datasets go through the cheap deterministic + internal-LLM bulk path; hard ones
(`route()=="claude"` or no deposited SDRF) are handed to the sdrf-skills agent. **Both** paths use
sdrf-skills `tools/` for external lookups and pass the **same review gate** before `merged`.

## Three ways to wire it (pick a depth)

**1. Loose coupling via MCP (fastest).** Run sdrf-skills' `mcp/server.py` and point the harness's
`fetcher`, evidence providers, and `ground` at those MCP tools instead of their own HTTP clients.
Nothing structural changes — it is the injected-provider pattern.

**2. Tier escalation (highest value) — implemented here as `handoff.py`.** When the harness escalates
a dataset, it queues a request an agent picks up; the agent annotates with `/sdrf:annotate` +
`/sdrf:adversarial-review` and writes the result + receipt back; the harness ingests it. See below.

**3. Shared-library extraction (cleanest long-term).** Both repos carry their own OLS client,
validators, and template logic. Extract the overlaps so they cannot drift:
- **Spec** — generate `template_snapshots.py` from sdrf-skills' `spec/` submodule (one source of truth
  for requirements + reserved words).
- **OLS** — one client (`tools/ols_client.py`) used by both.
- **Review gate** — `tools/review_gate.py` as the shared gate for both paths.

## The escalation hand-off (`handoff.py`)

The strong tier is asynchronous (an agent, not a synchronous `generate`), so it is a **file queue**,
one directory per accession under a shared root:

```
<root>/<ACCESSION>/request.json      # written by the harness
<root>/<ACCESSION>/result.sdrf.tsv   # written by the agent (finished SDRF)
<root>/<ACCESSION>/review.json       # written by the agent (adversarial-review receipt,
                                     #   bound to sha256(result), like the sdrf-skills review gate)
```

**Harness side — queue on escalation.** Wire an escalation writer into the batch loop:

```python
from sdrf_agentic_annotator import handoff
from sdrf_agentic_annotator.orchestrator import run_loop

on_escalate = handoff.make_escalation_writer(
    "/shared/handoff",
    build_messages=lambda acc: build_prompt(acc),   # the drafting prompt from evidence
    templates_of=lambda acc: templates_for(acc),    # optional
)
run_loop(ledger, corpus, "worker-1", 25, get_sdrf_text, now, on_escalate=on_escalate)
```

**Agent side — drain the queue.** For each accession in `handoff.pending("/shared/handoff")`, read its
`request.json` (it carries the prompt, target templates, and evidence), run the sdrf-skills
`/sdrf:annotate` then `/sdrf:adversarial-review` workflows, and write `result.sdrf.tsv` +
`review.json` back into that accession's directory. The receipt must be a *pass* and carry
`artifact_sha256` of the result (this is what `review_gate.py` produces).

**Harness side — ingest completed results.** Fold this into the next batch pass:

```python
for acc in ledger.escalated():                      # rows waiting on the agent
    done = handoff.ingest("/shared/handoff", acc)   # None until the agent finishes
    if done and done["passed"]:                     # pass + receipt bound to this exact SDRF
        stage_and_merge(corpus, acc, done["text"])  # merger.stage_sdrf / commit_batch
        ledger.set_status(acc, "merged")
```

`handoff.review_passed` enforces the sdrf-skills binding: a receipt is valid only for the exact SDRF
it was computed on (SHA-256), so a post-review edit invalidates it — the harness will not merge an
edited-after-approval artifact.

## What to unify first (prevent drift)

Both repos currently each carry an OLS client, validators, and template knowledge. When you combine
them, pick **one owner per concern** — sdrf-skills `spec/` for templates/TERMS, one OLS client, one
review gate — or a reserved-word / requirement change in one repo will silently disagree with the
other.
