# Start Here — roadmap for the next developer

Read [DEVELOPER.md](../DEVELOPER.md) (architecture + conventions) and
[docs/INTEGRATION.md](INTEGRATION.md) (sdrf-skills) first. This file is the **state of play** and the
**ordered backlog** — what is built, what is not yet wired, and what to build next.

## Where things stand

Everything is a **model-agnostic, unit-tested building block** (31 test files, `pytest -q` green,
offline). What is *missing* is composition into one end-to-end run.

| capability | module (built + tested) | wired into a runnable entry point? |
|---|---|---|
| work queue (claim/lease/reclaim, status lifecycle) | `ledger` | ✅ `run.py` |
| normalize a **deposited** SDRF → validate → merge | `orchestrator`, `normalizer`, `validator`, `merger` | ✅ `run.py` |
| fetch dataset → `Bundle` | `fetcher`, `harvester`, `models` | ✅ `run.py` |
| evidence + coverage + **tier routing** + per-dataset prompt | `evidence`, `coverage`, `batch.prepare`, `prompt` | ⚠️ `batch.prepare` emits a manifest, but nothing consumes it |
| **draft with an LLM** (validate→repair loop, techrefine, ground) | `draft`, `pipeline.draft_dataset` | ❌ not called from any runnable entry point |
| **internal PRIDE LLM** provider | `llm.get_generate("pride-internal")` | ❌ available, never invoked in a run |
| deterministic curation / grounding / PTMs / expand | `curate`, `ground`, `ptms`, `expand` | ✅ (as pipeline stages) |
| **escalation hand-off** to the sdrf-skills agent | `handoff`, `orchestrator.run_loop(on_escalate=…)` | ⚠️ writer hook exists; **ingest** not wired |

**In one sentence:** the deterministic spine and every stage are done and tested; the CLI currently
runs only the deposited-SDRF path, and the **LLM drafting path is not yet composed** even though all
its parts (prompt, internal LLM, repair loop, curation, validation, merge) exist.

## Do this first — P0: a self-contained drafting runner on the internal LLM

Because `llm.py` now has `pride-internal`, you can draft the **bulk (qwen) tier without the GPU
cluster**. Build the runner that ties the existing pieces together:

**What to build:** a `draft_runner` module + CLI subcommand that, for each dataset in
`batch.prepare`'s manifest:

```
qwen tier:   generate = llm.get_generate("pride-internal")
             result = pipeline.draft_dataset(acc, messages, generate,
                                              validate=draft.validate_text,
                                              refine_fn=ground.refine,           # ground/strip accessions
                                              techrefine_fn=None)                # optional, cluster-only
             if result["passed"]:  merger.stage_sdrf + commit ; ledger → merged
             else:                 handoff.write_request(...) ; ledger → escalate
claude tier: handoff.write_request(...) ; ledger → escalate   # hand to the sdrf-skills agent
```

**Reuse (do not rebuild):** `batch.prepare`, `llm.get_generate`, `pipeline.draft_dataset`,
`draft.validate_text`, `ground`, `curate`, `merger`, `handoff`, `ledger`.

**Acceptance:** `python -m sdrf_agentic_annotator.<runner> --manifest … --db … --corpus …` produces
validated SDRFs for the qwen tier via the internal LLM, and escalates + writes hand-offs for the rest.
Add a test that drives it with a **fake `generate`** (canned SDRF text) — no network.

**Size:** M. This is the single change that turns the repo from "a box of tested parts" into "an
end-to-end annotator", and it needs no cluster.

## Backlog (in priority order)

Each item: where to start · acceptance · size.

**P1 — Wire the hand-off ingest loop.**
Start: add `ledger.list_by_status("escalate")`, then a pass that calls `handoff.ingest(root, acc)` for
each and merges results where `passed` is true. · Acceptance: a completed+reviewed hand-off is merged
and the ledger row flips to `merged`; an unreviewed/edited one is not. · Size: S.

**P2 — Reuse sdrf-skills tools for evidence/grounding (INTEGRATION.md option 1).**
Start: a thin provider module that calls the sdrf-skills MCP server (`get_project_details`,
`get_full_text_article`, `searchClasses`/`getChildren`) and inject it into `evidence.build_evidence`
and `ground`. · Acceptance: the bulk path uses sdrf-skills tools with the same results, offline tests
still pass (mock the client). · Size: M.

**P3 — Single-source the spec.**
Start: generate `template_snapshots.py` from sdrf-skills' `spec/` submodule; add a CI check that they
match. · Acceptance: a reserved-word/requirement change in the spec fails CI here until regenerated. ·
Size: S–M.

**P4 — techrefine at scale.**
Start: `techrefine` download/quota bounding + cluster batch wiring (Thermo-only, per name-family,
representative subset). · Acceptance: enrichment runs on a batch within a fixed raw-file budget. ·
Size: M (needs Codon access).

**P5 — Hard-gap coverage.**
Start: `expand.py` fraction/replicate edge cases for large multiplexed datasets; wire paper full-text
mining (Europe PMC) for unfilled required columns before escalating. · Acceptance: fewer datasets
escalate for gaps a paper actually fills. · Size: M.

**P6 — One CLI.**
Start: a single entry (`harvest → prepare → draft-run → ingest`) so an operator runs one command per
batch. · Acceptance: end-to-end batch from an accessions file with one invocation. · Size: S.

## How to verify any change

- `pytest -q` stays **green and offline**. Add tests with fakes (inject `generate` / providers /
  `get_sdrf_text`); never call PRIDE/OLS/the LLM live in a test.
- For SDRF transforms, assert the header is byte-for-byte preserved and repeated columns survive.
- Live-check the internal LLM manually only (`llm.pride_llm_generate`) — it is EBI-network + proxy-
  bypass.

## Don'ts (the traps that bite silently)

- **Never write SDRF with `pandas.to_csv`** and never key rows by a non-unique column name — see
  DEVELOPER.md §5 (duplicate columns are load-bearing; reserved words; coordinate uniqueness;
  label↔accession agreement). This is the #1 source of wrong-but-valid output.
- Keep the test suite offline; keep every stage's injected-dependency shape (that is what makes it
  testable).
- Bound `techrefine` raw-file downloads.
- No AI-assistant attribution in commits/PRs; branch off `main`.

## Pointers

- Architecture, conventions, domain invariants → [DEVELOPER.md](../DEVELOPER.md)
- Combining with sdrf-skills (tools, review gate, escalation) → [docs/INTEGRATION.md](INTEGRATION.md)
